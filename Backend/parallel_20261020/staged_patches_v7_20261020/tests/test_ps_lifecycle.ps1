# test_ps_lifecycle.ps1 — disposable-copy lifecycle tests for the v7 apply/revert scripts
#
# Every test runs against COPIES of the production files in a temp directory.
# The production Unity files are never opened for writing by this script.
#
# Covered (the gaps named in the 2026-10-20 review of v4):
#   T1 apply commits a receipt
#   T2 second apply is idempotent
#   T3 same-content file at another path is refused (receipt target binding)
#   T4 an existing corrupt backup aborts the apply before any change
#   T5 a failed pending-receipt write aborts with the target unchanged
#   T6 a pending-only state is committed by the next apply
#   T7 edits after apply block revert; -SaveCurrentFirst archives then restores
#   T8 a pending-only state can still be reverted
#   T9 revert refuses a -TargetOverride that is not the receipt target
#   T10 a commit-write failure exits 12 (not 0), keeps the verified pending
#       receipt, and the next run commits it
#   T11 a recovery-commit failure exits 12 and leaves the pending state intact
#   T12 a truncated committed receipt does not block recovery from pending
#   T13 revert recovers from pending when the committed receipt is truncated
#   T14 an unreadable receipt with nothing to recover from refuses (exit 11)
#   T15 recovery with a missing backup refuses (exit 13) and writes no receipt
#   T16 recovery with a mismatched backup refuses (exit 13); once the backup is
#       repaired by hand the same state commits and records backup_sha256
#   T17 revert from a pending-only state refuses a damaged rollback record
#   T18 recovery with no pre_patch_hash refuses (exit 13)
#
# The commit failures are injected with the only filesystem lever that is
# deterministic here: `patch_receipt.json.tmp` is pre-created as a DIRECTORY, so
# the temp write cannot succeed. `Move-Item -Force` was measured to overwrite a
# read-only file and a read-only attribute does not block a rename, so a
# read-only receipt would not have exercised the failure path at all.

[CmdletBinding()]
param(
    [switch]$KeepWorkDir
)

$ErrorActionPreference = "Continue"

$packRoot = Split-Path -Parent $PSScriptRoot
$prodUdp = "C:\Users\QIYUXUAN\Desktop\Endless-Driver-Tutorial - EP9\Endless-Driver-Tutorial - EP9\Assets\BackEnd\UDPManager.cs"
$prodUi = "C:\Users\QIYUXUAN\Desktop\Endless-Driver-Tutorial - EP9\Endless-Driver-Tutorial - EP9\Assets\Endness Falling\Scripts\UIManager.cs"

$work = Join-Path $env:TEMP ("v7_ps_lifecycle_" + [System.Guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $work -Force | Out-Null

$script:pass = 0
$script:fail = 0
$script:lines = @()

function Get-Sha([string]$p) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $p).Hash
}

function Invoke-Step {
    param(
        [string]$Script,
        [hashtable]$Params,
        [string[]]$Switches = @()
    )
    $argv = @("-ExecutionPolicy", "Bypass", "-File", $Script)
    foreach ($k in $Params.Keys) {
        $argv += "-$k"
        $argv += [string]$Params[$k]
    }
    foreach ($s in $Switches) { $argv += "-$s" }
    $out = & powershell @argv 2>&1
    return [PSCustomObject]@{ code = $LASTEXITCODE; out = (($out | Out-String).Trim()) }
}

function Check {
    param([string]$Name, [bool]$Condition, [string]$Detail = "")
    if ($Condition) {
        $script:pass++
        $script:lines += ("  [PASS] {0}" -f $Name)
    } else {
        $script:fail++
        $script:lines += ("  [FAIL] {0} {1}" -f $Name, $Detail)
    }
}

function New-Case([string]$Name) {
    $dir = Join-Path $work $Name
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    return $dir
}

function Reset-Target([string]$CaseDir, [string]$ProdPath, [string]$Leaf) {
    $t = Join-Path $CaseDir $Leaf
    Copy-Item -LiteralPath $ProdPath -Destination $t -Force
    Set-ItemProperty -LiteralPath $t -Name IsReadOnly -Value $false -ErrorAction SilentlyContinue
    return $t
}

# The pending state a crash between replacement and commit would leave behind.
function Write-Pending([string]$CaseDir, [string]$Target, [string]$PreHash, [string]$PostHash) {
    $bkFile = (Get-ChildItem -Path (Join-Path $CaseDir "bk") -Filter "*.bak" | Select-Object -First 1).FullName
    $pend = [PSCustomObject]@{
        target             = $Target
        pre_patch_hash     = $PreHash
        intended_post_hash = $PostHash
        backup_file        = $bkFile
        written_at_utc     = [System.DateTime]::UtcNow.ToString("o")
        state              = "pending"
    }
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText((Join-Path $CaseDir "patch_receipt.pending.json"),
        ($pend | ConvertTo-Json -Depth 4), $utf8)
}

# Same, with arbitrary fields, for the damaged-rollback-record fixtures.
function Write-PendingCustom([string]$CaseDir, $Fields) {
    $pend = [PSCustomObject]$Fields
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText((Join-Path $CaseDir "patch_receipt.pending.json"),
        ($pend | ConvertTo-Json -Depth 4), $utf8)
}

# Blocks the verified temp receipt, which is the only way this environment can
# make a commit fail after the target has already been replaced.
function Block-Commit([string]$CaseDir) {
    $p = Join-Path $CaseDir "patch_receipt.json.tmp"
    New-Item -ItemType Directory -Path $p -Force | Out-Null
    return $p
}

function Unblock-Commit([string]$Blocker) {
    if (Test-Path -LiteralPath $Blocker -PathType Container) {
        Remove-Item -LiteralPath $Blocker -Force -Recurse -ErrorAction SilentlyContinue
    } elseif (Test-Path -LiteralPath $Blocker) {
        Remove-Item -LiteralPath $Blocker -Force -ErrorAction SilentlyContinue
    }
}

$cases = @(
    @{ name = "p1"; prod = $prodUdp; leaf = "UDPManager.cs"; apply = "$packRoot\patch_1_terminal_delivery\apply.ps1"; revert = "$packRoot\patch_1_terminal_delivery\revert.ps1" },
    @{ name = "p2"; prod = $prodUi;  leaf = "UIManager.cs";  apply = "$packRoot\patch_2_uimanager_style_cache\apply.ps1"; revert = "$packRoot\patch_2_uimanager_style_cache\revert.ps1" }
)

"=== v7 PowerShell lifecycle tests ==="
"work dir: $work"

foreach ($c in $cases) {
    $script:lines += ""
    $script:lines += ("--- {0} ({1}) ---" -f $c.name, (Split-Path $c.leaf -Leaf))
    $preHash = Get-Sha $c.prod

    # T1 + T2 -----------------------------------------------------------------
    $d = New-Case "$($c.name)_t12"
    $t = Reset-Target $d $c.prod $c.leaf
    $r = Invoke-Step -Script $c.apply -Params @{ TargetOverride = $t; ReceiptDir = $d; BackupDir = (Join-Path $d "bk") }
    $postHash = Get-Sha $t
    Check "T1 apply exit 0" ($r.code -eq 0) ("exit=$($r.code): " + $r.out)
    Check "T1 target changed" ($postHash -ne $preHash) "hash still $postHash"
    Check "T1 committed receipt exists" (Test-Path -LiteralPath (Join-Path $d "patch_receipt.json"))
    Check "T1 pending receipt removed" (-not (Test-Path -LiteralPath (Join-Path $d "patch_receipt.pending.json")))
    $rec = Get-Content -LiteralPath (Join-Path $d "patch_receipt.json") -Raw | ConvertFrom-Json
    Check "T1 receipt post hash matches file" ($rec.post_patch_hash -eq $postHash) "receipt=$($rec.post_patch_hash) file=$postHash"
    Check "T1 receipt target matches" ((Get-Sha $rec.target) -eq $postHash) "receipt target=$($rec.target)"

    $r2 = Invoke-Step -Script $c.apply -Params @{ TargetOverride = $t; ReceiptDir = $d; BackupDir = (Join-Path $d "bk") }
    Check "T2 second apply exit 0" ($r2.code -eq 0) ("exit=$($r2.code): " + $r2.out)
    Check "T2 second apply did not change the file" ((Get-Sha $t) -eq $postHash)

    # T3 target binding -------------------------------------------------------
    $d3 = New-Case "$($c.name)_t3"
    $t3a = Reset-Target $d3 $c.prod $c.leaf
    $t3b = Join-Path $d3 ("other_" + $c.leaf)
    Copy-Item -LiteralPath $t3a -Destination $t3b -Force
    $null = Invoke-Step -Script $c.apply -Params @{ TargetOverride = $t3a; ReceiptDir = $d3; BackupDir = (Join-Path $d3 "bk") }
    $t3bHashBefore = Get-Sha $t3b
    $r3 = Invoke-Step -Script $c.apply -Params @{ TargetOverride = $t3b; ReceiptDir = $d3; BackupDir = (Join-Path $d3 "bk") }
    Check "T3 apply to same-content other path refused" ($r3.code -eq 8) ("exit=$($r3.code)")
    Check "T3 other file untouched" ((Get-Sha $t3b) -eq $t3bHashBefore)

    # T4 corrupt existing backup ---------------------------------------------
    $d4 = New-Case "$($c.name)_t4"
    $t4 = Reset-Target $d4 $c.prod $c.leaf
    $bk4 = Join-Path $d4 "bk"
    New-Item -ItemType Directory -Path $bk4 -Force | Out-Null
    $pre16 = $preHash.Substring(0, 16)
    $bkName = if ($c.name -eq "p1") { "UDPManager.cs.pre_$pre16.bak" } else { "UIManager.cs.pre_$pre16.bak" }
    Set-Content -LiteralPath (Join-Path $bk4 $bkName) -Value "not the original source" -Encoding utf8
    $r4 = Invoke-Step -Script $c.apply -Params @{ TargetOverride = $t4; ReceiptDir = $d4; BackupDir = $bk4 }
    Check "T4 corrupt backup aborts (exit 6)" ($r4.code -eq 6) ("exit=$($r4.code)")
    Check "T4 target untouched" ((Get-Sha $t4) -eq $preHash)
    Check "T4 no receipt written" (-not (Test-Path -LiteralPath (Join-Path $d4 "patch_receipt.json")))

    # T5 pending-receipt write failure ---------------------------------------
    $d5 = New-Case "$($c.name)_t5"
    $t5 = Reset-Target $d5 $c.prod $c.leaf
    $blocked = Join-Path $d5 "blocked_dir"
    Set-Content -LiteralPath $blocked -Value "this is a file, not a directory" -Encoding utf8
    $r5 = Invoke-Step -Script $c.apply -Params @{ TargetOverride = $t5; ReceiptDir = $blocked; BackupDir = (Join-Path $d5 "bk") }
    Check "T5 unwritable receipt dir aborts (exit 7)" ($r5.code -eq 7) ("exit=$($r5.code): " + $r5.out)
    Check "T5 target untouched" ((Get-Sha $t5) -eq $preHash)

    # T6 pending-only -> committed by next apply ------------------------------
    $d6 = New-Case "$($c.name)_t6"
    $t6 = Reset-Target $d6 $c.prod $c.leaf
    $null = Invoke-Step -Script $c.apply -Params @{ TargetOverride = $t6; ReceiptDir = $d6; BackupDir = (Join-Path $d6 "bk") }
    $appliedHash = Get-Sha $t6
    Remove-Item -LiteralPath (Join-Path $d6 "patch_receipt.json") -Force
    Write-Pending $d6 $t6 $preHash $appliedHash
    $r6 = Invoke-Step -Script $c.apply -Params @{ TargetOverride = $t6; ReceiptDir = $d6; BackupDir = (Join-Path $d6 "bk") }
    Check "T6 pending state recovered (exit 0)" ($r6.code -eq 0) ("exit=$($r6.code)")
    Check "T6 committed receipt now exists" (Test-Path -LiteralPath (Join-Path $d6 "patch_receipt.json"))
    Check "T6 pending cleared" (-not (Test-Path -LiteralPath (Join-Path $d6 "patch_receipt.pending.json")))

    # T7 edit after apply -> refuse, then -SaveCurrentFirst -------------------
    $d7 = New-Case "$($c.name)_t7"
    $t7 = Reset-Target $d7 $c.prod $c.leaf
    $null = Invoke-Step -Script $c.apply -Params @{ TargetOverride = $t7; ReceiptDir = $d7; BackupDir = (Join-Path $d7 "bk") }
    Add-Content -LiteralPath $t7 -Value "// reviewer edit after patch"
    $editedHash = Get-Sha $t7
    $r7a = Invoke-Step -Script $c.revert -Params @{ ReceiptDir = $d7; BackupDir = (Join-Path $d7 "bk") }
    Check "T7 revert refuses edited target (exit 1)" ($r7a.code -eq 1) ("exit=$($r7a.code)")
    Check "T7 edited target untouched by refusal" ((Get-Sha $t7) -eq $editedHash)
    $r7b = Invoke-Step -Script $c.revert -Params @{ ReceiptDir = $d7; BackupDir = (Join-Path $d7 "bk") } -Switches @("SaveCurrentFirst")
    Check "T7 revert -SaveCurrentFirst restores (exit 0)" ($r7b.code -eq 0) ("exit=$($r7b.code): " + $r7b.out)
    Check "T7 restored to pre-patch hash" ((Get-Sha $t7) -eq $preHash) ("got " + (Get-Sha $t7))
    $archived = Get-ChildItem -Path (Join-Path $d7 "bk") -Filter "*.edited_*.bak" -ErrorAction SilentlyContinue
    Check "T7 edited version archived" ($null -ne $archived -and @($archived).Count -ge 1)

    # T8 pending-only revert ------------------------------------------------
    $d8 = New-Case "$($c.name)_t8"
    $t8 = Reset-Target $d8 $c.prod $c.leaf
    $null = Invoke-Step -Script $c.apply -Params @{ TargetOverride = $t8; ReceiptDir = $d8; BackupDir = (Join-Path $d8 "bk") }
    $applied8 = Get-Sha $t8
    Remove-Item -LiteralPath (Join-Path $d8 "patch_receipt.json") -Force
    Write-Pending $d8 $t8 $preHash $applied8
    $r8 = Invoke-Step -Script $c.revert -Params @{ ReceiptDir = $d8; BackupDir = (Join-Path $d8 "bk") }
    Check "T8 pending-only revert restores (exit 0)" ($r8.code -eq 0) ("exit=$($r8.code): " + $r8.out)
    Check "T8 restored to pre-patch hash" ((Get-Sha $t8) -eq $preHash)

    # T9 revert -TargetOverride must equal receipt target --------------------
    $d9 = New-Case "$($c.name)_t9"
    $t9 = Reset-Target $d9 $c.prod $c.leaf
    $t9b = Join-Path $d9 ("decoy_" + $c.leaf)
    Copy-Item -LiteralPath $t9 -Destination $t9b -Force
    $null = Invoke-Step -Script $c.apply -Params @{ TargetOverride = $t9; ReceiptDir = $d9; BackupDir = (Join-Path $d9 "bk") }
    $decoyBefore = Get-Sha $t9b
    $r9 = Invoke-Step -Script $c.revert -Params @{ TargetOverride = $t9b; ReceiptDir = $d9; BackupDir = (Join-Path $d9 "bk") }
    Check "T9 revert with foreign override refused (exit 8)" ($r9.code -eq 8) ("exit=$($r9.code)")
    Check "T9 decoy untouched" ((Get-Sha $t9b) -eq $decoyBefore)

    # T10 initial commit-write failure ---------------------------------------
    $d10 = New-Case "$($c.name)_t10"
    $t10 = Reset-Target $d10 $c.prod $c.leaf
    $blocker10 = Block-Commit $d10
    $r10 = Invoke-Step -Script $c.apply -Params @{ TargetOverride = $t10; ReceiptDir = $d10; BackupDir = (Join-Path $d10 "bk") }
    Check "T10 commit write failure exits 12, not 0" ($r10.code -eq 12) ("exit=$($r10.code): " + $r10.out)
    $patched10 = Get-Sha $t10
    Check "T10 target was replaced before the commit failed" ($patched10 -ne $preHash)
    Check "T10 no committed receipt" (-not (Test-Path -LiteralPath (Join-Path $d10 "patch_receipt.json")))
    Check "T10 pending receipt retained" (Test-Path -LiteralPath (Join-Path $d10 "patch_receipt.pending.json"))
    $pend10 = Get-Content -LiteralPath (Join-Path $d10 "patch_receipt.pending.json") -Raw | ConvertFrom-Json
    Check "T10 retained pending still binds the patched target" ($pend10.target -eq $t10 -and $pend10.intended_post_hash -eq $patched10)
    Unblock-Commit $blocker10
    $r10b = Invoke-Step -Script $c.apply -Params @{ TargetOverride = $t10; ReceiptDir = $d10; BackupDir = (Join-Path $d10 "bk") }
    Check "T10 next run recovers from pending (exit 0)" ($r10b.code -eq 0) ("exit=$($r10b.code): " + $r10b.out)
    Check "T10 committed receipt now exists" (Test-Path -LiteralPath (Join-Path $d10 "patch_receipt.json"))
    Check "T10 pending cleared after verified commit" (-not (Test-Path -LiteralPath (Join-Path $d10 "patch_receipt.pending.json")))

    # T11 recovery-commit failure --------------------------------------------
    $d11 = New-Case "$($c.name)_t11"
    $t11 = Reset-Target $d11 $c.prod $c.leaf
    $null = Invoke-Step -Script $c.apply -Params @{ TargetOverride = $t11; ReceiptDir = $d11; BackupDir = (Join-Path $d11 "bk") }
    $applied11 = Get-Sha $t11
    Remove-Item -LiteralPath (Join-Path $d11 "patch_receipt.json") -Force
    Write-Pending $d11 $t11 $preHash $applied11
    $blocker11 = Block-Commit $d11
    $r11 = Invoke-Step -Script $c.apply -Params @{ TargetOverride = $t11; ReceiptDir = $d11; BackupDir = (Join-Path $d11 "bk") }
    Check "T11 recovery commit failure exits 12" ($r11.code -eq 12) ("exit=$($r11.code): " + $r11.out)
    Check "T11 committed receipt still absent" (-not (Test-Path -LiteralPath (Join-Path $d11 "patch_receipt.json")))
    Check "T11 pending receipt still present" (Test-Path -LiteralPath (Join-Path $d11 "patch_receipt.pending.json"))
    Check "T11 target still in the patched state" ((Get-Sha $t11) -eq $applied11)
    Unblock-Commit $blocker11
    $r11b = Invoke-Step -Script $c.apply -Params @{ TargetOverride = $t11; ReceiptDir = $d11; BackupDir = (Join-Path $d11 "bk") }
    Check "T11 recovery succeeds once writable (exit 0)" ($r11b.code -eq 0) ("exit=$($r11b.code): " + $r11b.out)
    Check "T11 committed receipt written on the retry" (Test-Path -LiteralPath (Join-Path $d11 "patch_receipt.json"))

    # T12 truncated committed receipt + valid pending -------------------------
    $d12 = New-Case "$($c.name)_t12"
    $t12 = Reset-Target $d12 $c.prod $c.leaf
    $null = Invoke-Step -Script $c.apply -Params @{ TargetOverride = $t12; ReceiptDir = $d12; BackupDir = (Join-Path $d12 "bk") }
    $applied12 = Get-Sha $t12
    Set-Content -LiteralPath (Join-Path $d12 "patch_receipt.json") -Value '{"target": "' -Encoding utf8
    Write-Pending $d12 $t12 $preHash $applied12
    $r12 = Invoke-Step -Script $c.apply -Params @{ TargetOverride = $t12; ReceiptDir = $d12; BackupDir = (Join-Path $d12 "bk") }
    Check "T12 truncated committed receipt does not block recovery (exit 0)" ($r12.code -eq 0) ("exit=$($r12.code): " + $r12.out)
    $rec12 = $null
    try { $rec12 = Get-Content -LiteralPath (Join-Path $d12 "patch_receipt.json") -Raw | ConvertFrom-Json } catch { $rec12 = $null }
    Check "T12 committed receipt readable and bound again" ($null -ne $rec12 -and $rec12.post_patch_hash -eq $applied12 -and $rec12.target -eq $t12)
    $q12 = Get-ChildItem -Path $d12 -Filter "patch_receipt.corrupt_*.json" -ErrorAction SilentlyContinue
    Check "T12 truncated receipt quarantined, not discarded" ($null -ne $q12 -and @($q12).Count -ge 1)

    # T13 revert recovers from pending when the committed receipt is truncated
    $d13 = New-Case "$($c.name)_t13"
    $t13 = Reset-Target $d13 $c.prod $c.leaf
    $null = Invoke-Step -Script $c.apply -Params @{ TargetOverride = $t13; ReceiptDir = $d13; BackupDir = (Join-Path $d13 "bk") }
    $applied13 = Get-Sha $t13
    Set-Content -LiteralPath (Join-Path $d13 "patch_receipt.json") -Value 'not json at all' -Encoding utf8
    Write-Pending $d13 $t13 $preHash $applied13
    $r13 = Invoke-Step -Script $c.revert -Params @{ ReceiptDir = $d13; BackupDir = (Join-Path $d13 "bk") }
    Check "T13 revert recovers from pending (exit 0)" ($r13.code -eq 0) ("exit=$($r13.code): " + $r13.out)
    Check "T13 restored to the pre-patch hash" ((Get-Sha $t13) -eq $preHash) ("got " + (Get-Sha $t13))

    # T14 nothing recoverable -> refuse instead of acting on a null receipt --
    $d14 = New-Case "$($c.name)_t14"
    $t14 = Reset-Target $d14 $c.prod $c.leaf
    $null = Invoke-Step -Script $c.apply -Params @{ TargetOverride = $t14; ReceiptDir = $d14; BackupDir = (Join-Path $d14 "bk") }
    $applied14 = Get-Sha $t14
    Set-Content -LiteralPath (Join-Path $d14 "patch_receipt.json") -Value '{"target": "' -Encoding utf8
    $r14a = Invoke-Step -Script $c.apply -Params @{ TargetOverride = $t14; ReceiptDir = $d14; BackupDir = (Join-Path $d14 "bk") }
    Check "T14 unreadable receipt with no pending refuses (exit 11)" ($r14a.code -eq 11) ("exit=$($r14a.code)")
    $r14b = Invoke-Step -Script $c.revert -Params @{ ReceiptDir = $d14; BackupDir = (Join-Path $d14 "bk") }
    Check "T14 revert refuses the same state (exit 11)" ($r14b.code -eq 11) ("exit=$($r14b.code)")
    Check "T14 target untouched by the refusals" ((Get-Sha $t14) -eq $applied14)

    # T15 pending recovery with a MISSING backup ------------------------------
    # A promoted receipt would claim a rollback point that does not exist.
    $d15 = New-Case "$($c.name)_t15"
    $t15 = Reset-Target $d15 $c.prod $c.leaf
    $null = Invoke-Step -Script $c.apply -Params @{ TargetOverride = $t15; ReceiptDir = $d15; BackupDir = (Join-Path $d15 "bk") }
    $applied15 = Get-Sha $t15
    $bk15 = (Get-ChildItem -Path (Join-Path $d15 "bk") -Filter "*.bak" | Select-Object -First 1).FullName
    Remove-Item -LiteralPath (Join-Path $d15 "patch_receipt.json") -Force
    Write-PendingCustom $d15 ([ordered]@{
        target             = $t15
        pre_patch_hash     = $preHash
        intended_post_hash = $applied15
        backup_file        = (Join-Path $d15 "bk\does_not_exist.bak")
        written_at_utc     = [System.DateTime]::UtcNow.ToString("o")
        state              = "pending"
    })
    $pendBefore15 = Get-Sha (Join-Path $d15 "patch_receipt.pending.json")
    $r15 = Invoke-Step -Script $c.apply -Params @{ TargetOverride = $t15; ReceiptDir = $d15; BackupDir = (Join-Path $d15 "bk") }
    Check "T15 recovery with a missing backup refuses (exit 13)" ($r15.code -eq 13) ("exit=$($r15.code): " + $r15.out)
    Check "T15 no committed receipt was written" (-not (Test-Path -LiteralPath (Join-Path $d15 "patch_receipt.json")))
    Check "T15 pending receipt kept byte-identical" ((Get-Sha (Join-Path $d15 "patch_receipt.pending.json")) -eq $pendBefore15)
    Check "T15 target still in the patched state" ((Get-Sha $t15) -eq $applied15)
    Check "T15 the missing path is named" ($r15.out -match [regex]::Escape("does_not_exist.bak"))

    # T16 pending recovery with a CORRUPTED backup (hash mismatch) ------------
    $d16 = New-Case "$($c.name)_t16"
    $t16 = Reset-Target $d16 $c.prod $c.leaf
    $null = Invoke-Step -Script $c.apply -Params @{ TargetOverride = $t16; ReceiptDir = $d16; BackupDir = (Join-Path $d16 "bk") }
    $applied16 = Get-Sha $t16
    $bk16 = (Get-ChildItem -Path (Join-Path $d16 "bk") -Filter "*.bak" | Select-Object -First 1).FullName
    Remove-Item -LiteralPath (Join-Path $d16 "patch_receipt.json") -Force
    Write-Pending $d16 $t16 $preHash $applied16
    Set-ItemProperty -LiteralPath $bk16 -Name IsReadOnly -Value $false -ErrorAction SilentlyContinue
    Add-Content -LiteralPath $bk16 -Value "// tampered" -Encoding utf8
    $r16 = Invoke-Step -Script $c.apply -Params @{ TargetOverride = $t16; ReceiptDir = $d16; BackupDir = (Join-Path $d16 "bk") }
    Check "T16 recovery with a mismatched backup refuses (exit 13)" ($r16.code -eq 13) ("exit=$($r16.code): " + $r16.out)
    Check "T16 no committed receipt was written" (-not (Test-Path -LiteralPath (Join-Path $d16 "patch_receipt.json")))
    Check "T16 pending receipt retained" (Test-Path -LiteralPath (Join-Path $d16 "patch_receipt.pending.json"))
    Check "T16 the hash mismatch is named" ((($r16.out -replace "\s+", " ")) -match "not the recorded pre-patch state")
    # Repair the rollback point (the pre-patch bytes are still the production copy).
    Copy-Item -LiteralPath $c.prod -Destination $bk16 -Force
    $r16b = Invoke-Step -Script $c.apply -Params @{ TargetOverride = $t16; ReceiptDir = $d16; BackupDir = (Join-Path $d16 "bk") }
    Check "T16 recovery commits once the backup verifies (exit 0)" ($r16b.code -eq 0) ("exit=$($r16b.code): " + $r16b.out)
    $rec16 = $null
    try { $rec16 = Get-Content -LiteralPath (Join-Path $d16 "patch_receipt.json") -Raw | ConvertFrom-Json } catch { $rec16 = $null }
    Check "T16 receipt records a verified backup" ($null -ne $rec16 -and $rec16.backup_verified -eq $true -and $rec16.backup_sha256 -eq $preHash)
    Check "T16 receipt targets the patched file" ($null -ne $rec16 -and $rec16.post_patch_hash -eq $applied16)

    # T17 revert from a pending-only state with a damaged backup --------------
    $d17 = New-Case "$($c.name)_t17"
    $t17 = Reset-Target $d17 $c.prod $c.leaf
    $null = Invoke-Step -Script $c.apply -Params @{ TargetOverride = $t17; ReceiptDir = $d17; BackupDir = (Join-Path $d17 "bk") }
    $applied17 = Get-Sha $t17
    $bk17 = (Get-ChildItem -Path (Join-Path $d17 "bk") -Filter "*.bak" | Select-Object -First 1).FullName
    Remove-Item -LiteralPath (Join-Path $d17 "patch_receipt.json") -Force
    Write-Pending $d17 $t17 $preHash $applied17
    Set-ItemProperty -LiteralPath $bk17 -Name IsReadOnly -Value $false -ErrorAction SilentlyContinue
    Add-Content -LiteralPath $bk17 -Value "// tampered" -Encoding utf8
    $r17 = Invoke-Step -Script $c.revert -Params @{ ReceiptDir = $d17; BackupDir = (Join-Path $d17 "bk") }
    Check "T17 revert refuses a damaged rollback record (exit 13)" ($r17.code -eq 13) ("exit=$($r17.code): " + $r17.out)
    Check "T17 target untouched by the refusal" ((Get-Sha $t17) -eq $applied17)
    Check "T17 the defect is named" ((($r17.out -replace "\s+", " ")) -match "cannot serve as a rollback record")

    # T18 pending recovery with an incomplete hash record ---------------------
    $d18 = New-Case "$($c.name)_t18"
    $t18 = Reset-Target $d18 $c.prod $c.leaf
    $null = Invoke-Step -Script $c.apply -Params @{ TargetOverride = $t18; ReceiptDir = $d18; BackupDir = (Join-Path $d18 "bk") }
    $applied18 = Get-Sha $t18
    $bk18 = (Get-ChildItem -Path (Join-Path $d18 "bk") -Filter "*.bak" | Select-Object -First 1).FullName
    Remove-Item -LiteralPath (Join-Path $d18 "patch_receipt.json") -Force
    Write-PendingCustom $d18 ([ordered]@{
        target             = $t18
        intended_post_hash = $applied18
        backup_file        = $bk18
        written_at_utc     = [System.DateTime]::UtcNow.ToString("o")
        state              = "pending"
    })
    $r18 = Invoke-Step -Script $c.apply -Params @{ TargetOverride = $t18; ReceiptDir = $d18; BackupDir = (Join-Path $d18 "bk") }
    Check "T18 recovery with no pre_patch_hash refuses (exit 13)" ($r18.code -eq 13) ("exit=$($r18.code): " + $r18.out)
    Check "T18 no committed receipt was written" (-not (Test-Path -LiteralPath (Join-Path $d18 "patch_receipt.json")))
    Check "T18 the missing field is named" ((($r18.out -replace "\s+", " ")) -match "pre_patch_hash is missing")
}

$script:lines | ForEach-Object { $_ }
""
"=== result: $($script:pass) passed, $($script:fail) failed ==="
"production files: UDPManager $((Get-Sha $prodUdp).Substring(0,16)) | UIManager $((Get-Sha $prodUi).Substring(0,16))"

if (-not $KeepWorkDir) {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}

if ($script:fail -gt 0) { exit 1 } else { exit 0 }
