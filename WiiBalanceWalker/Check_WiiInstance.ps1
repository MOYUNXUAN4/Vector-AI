$ErrorActionPreference = 'Stop'

function Get-WiiProcessSnapshot {
    @(Get-CimInstance Win32_Process -Filter "Name='WiiBalanceWalker.exe'" -ErrorAction Stop |
        Select-Object ProcessId, Name, ThreadCount, HandleCount, CreationDate)
}

function Test-NonExecutingEntry($Entry, [datetime]$NowUtc) {
    if ($null -eq $Entry.ThreadCount -or $null -eq $Entry.HandleCount -or
        $null -eq $Entry.CreationDate) { return $false }
    if ([long]$Entry.ThreadCount -ne 0 -or [long]$Entry.HandleCount -ne 0) { return $false }
    $age = ($NowUtc - ([datetime]$Entry.CreationDate).ToUniversalTime()).TotalSeconds
    return $age -ge 5
}

function Get-WiiInstanceDecision($First, $Second, [datetime]$NowUtc) {
    $ignored = @()
    $blocking = @()
    foreach ($current in @($Second)) {
        $previous = @($First | Where-Object {
            $_.ProcessId -eq $current.ProcessId -and
            $_.CreationDate -eq $current.CreationDate
        })
        if ($previous.Count -eq 1 -and
            (Test-NonExecutingEntry $previous[0] $NowUtc) -and
            (Test-NonExecutingEntry $current $NowUtc)) {
            $ignored += [long]$current.ProcessId
        }
        else {
            $blocking += [long]$current.ProcessId
        }
    }
    [pscustomobject]@{IgnoredNonExecutingPids=$ignored; BlockingPids=$blocking}
}

try {
    $first = @(Get-WiiProcessSnapshot)
    if ($first.Count -eq 0) {
        Write-Output '[WII INSTANCE] No WiiBalanceWalker process is listed; startup may continue.'
        exit 0
    }
    Start-Sleep -Milliseconds 250
    $second = @(Get-WiiProcessSnapshot)
    $decision = Get-WiiInstanceDecision $first $second ([datetime]::UtcNow)
    foreach ($processId in $decision.IgnoredNonExecutingPids) {
        Write-Output ('[WII INSTANCE] Ignoring stable non-executing OS entry: PID ' + $processId + ' (zero threads/handles).')
    }
    if ($decision.BlockingPids.Count -gt 0) {
        Write-Output ('[WII INSTANCE BLOCKED] Existing or not-yet-verifiable instance, PID: ' + ($decision.BlockingPids -join ', '))
        Write-Output 'Close or restore that application before starting another instance. No process was terminated.'
        exit 1
    }
    Write-Output '[WII INSTANCE] No executing instance found; startup may continue.'
    exit 0
}
catch {
    [Console]::Error.WriteLine('[WII INSTANCE BLOCKED] Cannot verify process state: ' + $_.Exception.Message)
    exit 2
}
