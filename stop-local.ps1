[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$stateFile = Join-Path $PSScriptRoot '.local-hakuneko.json'
$electronExecutable = (Join-Path $PSScriptRoot 'node_modules\electron\dist\electron.exe').ToLowerInvariant()
$processIDs = [Collections.Generic.HashSet[int]]::new()

if (Test-Path -LiteralPath $stateFile -PathType Leaf) {
    try {
        $state = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
        if ($state.ServerPID) { [void] $processIDs.Add([int] $state.ServerPID) }
        if ($state.ElectronPID) { [void] $processIDs.Add([int] $state.ElectronPID) }
    } catch {
        Write-Warning "Could not read local state: $($_.Exception.Message)"
    }
}

# Also find detached helper processes from this repository's Electron binary.
$localElectron = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'electron.exe' -and
    $_.ExecutablePath -and
    $_.ExecutablePath.ToLowerInvariant() -eq $electronExecutable
})
foreach ($process in $localElectron) {
    [void] $processIDs.Add([int] $process.ProcessId)
}

# Clean up an orphaned Vite server only when it owns this launcher's port.
$listeners = @(Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue)
foreach ($listener in $listeners) {
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)" -ErrorAction SilentlyContinue
    if ($owner.CommandLine -like '*vite*preview*5000*') {
        [void] $processIDs.Add([int] $owner.ProcessId)
    }
}

$stopped = 0
foreach ($processID in $processIDs) {
    if (Get-Process -Id $processID -ErrorAction SilentlyContinue) {
        Stop-Process -Id $processID -Force
        $stopped++
    }
}

Remove-Item -LiteralPath $stateFile -Force -ErrorAction SilentlyContinue
Write-Host "Stopped $stopped local HakuNeko process(es)."
