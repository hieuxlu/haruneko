[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not ('LocalHakuNeko.NativeWindow' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace LocalHakuNeko {
    public static class NativeWindow {
        [DllImport("user32.dll")]
        public static extern bool ShowWindowAsync(IntPtr window, int command);
        [DllImport("user32.dll")]
        public static extern bool SetForegroundWindow(IntPtr window);
    }
}
'@
}

function Show-HakuNekoWindow {
    param([Parameter(Mandatory)] [int] $ProcessID)

    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        $process = Get-Process -Id $ProcessID -ErrorAction SilentlyContinue
        if (-not $process) { return $false }
        $process.Refresh()
        if ($process.MainWindowHandle -ne [IntPtr]::Zero) {
            # SW_RESTORE = 9
            [void] [LocalHakuNeko.NativeWindow]::ShowWindowAsync($process.MainWindowHandle, 9)
            [void] [LocalHakuNeko.NativeWindow]::SetForegroundWindow($process.MainWindowHandle)
            return $true
        }
        Start-Sleep -Milliseconds 250
    }
    return $false
}

$webBuild = Join-Path $PSScriptRoot 'web\build\index.html'
$electronBuild = Join-Path $PSScriptRoot 'app\electron\build\main.js'
$viteScript = Join-Path $PSScriptRoot 'node_modules\vite\bin\vite.js'
$viteScriptRelative = '..\node_modules\vite\bin\vite.js'
$electronExecutable = Join-Path $PSScriptRoot 'node_modules\electron\dist\electron.exe'
$stateFile = Join-Path $PSScriptRoot '.local-hakuneko.json'
$serverOutputLog = Join-Path $PSScriptRoot '.local-hakuneko-server.log'
$serverErrorLog = Join-Path $PSScriptRoot '.local-hakuneko-server.error.log'
$electronOutputLog = Join-Path $PSScriptRoot '.local-hakuneko-electron.log'
$electronErrorLog = Join-Path $PSScriptRoot '.local-hakuneko-electron.error.log'

foreach ($requiredFile in @($webBuild, $electronBuild, $viteScript, $electronExecutable)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Missing build dependency: $requiredFile. Run npm install, then build the web and Electron workspaces."
    }
}

if (Test-Path -LiteralPath $stateFile -PathType Leaf) {
    try {
        $previousState = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
        $previousElectron = if ($previousState.ElectronPID) {
            Get-Process -Id $previousState.ElectronPID -ErrorAction SilentlyContinue
        }
        if ($previousElectron) {
            Write-Host "Patched HakuNeko is already running (PID $($previousElectron.Id))."
            if (-not (Show-HakuNekoWindow -ProcessID $previousElectron.Id)) {
                Write-Host 'Find it on the taskbar, in the notification area, or with Alt+Tab.'
            }
            Write-Host 'Run .\stop-local.ps1 before starting a fresh instance.'
            return
        }

        $previousServer = if ($previousState.ServerPID) {
            Get-Process -Id $previousState.ServerPID -ErrorAction SilentlyContinue
        }
        if ($previousServer) {
            Stop-Process -Id $previousServer.Id
            $previousServer.WaitForExit()
        }
    } catch {
        Write-Warning "Ignoring stale local state: $($_.Exception.Message)"
    }
    Remove-Item -LiteralPath $stateFile -Force -ErrorAction SilentlyContinue
}

$nodeExecutable = (Get-Command node -ErrorAction Stop).Source
$server = Start-Process -FilePath $nodeExecutable `
    -ArgumentList @($viteScriptRelative, 'preview', '--host=127.0.0.1', '--port=5000', '--strictPort') `
    -WorkingDirectory (Join-Path $PSScriptRoot 'web') `
    -WindowStyle Hidden `
    -RedirectStandardOutput $serverOutputLog `
    -RedirectStandardError $serverErrorLog `
    -PassThru

@{ ServerPID = $server.Id; ElectronPID = $null } |
    ConvertTo-Json | Set-Content -LiteralPath $stateFile

try {
    $ready = $false
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
        if ($server.HasExited) {
            $details = Get-Content -LiteralPath $serverErrorLog -Raw -ErrorAction SilentlyContinue
            throw "The local web server exited with code $($server.ExitCode). $details"
        }
        try {
            $listener = Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction Stop |
                Where-Object { $_.OwningProcess -eq $server.Id } |
                Select-Object -First 1
            if ($listener) {
                $ready = $true
                break
            }
        } catch {
            # Server is still starting.
        }
        Start-Sleep -Milliseconds 250
    }

    if (-not $ready) {
        $details = Get-Content -LiteralPath $serverErrorLog -Raw -ErrorAction SilentlyContinue
        throw "The local web server did not become ready within 30 seconds. $details"
    }

    Write-Host 'Launching patched HakuNeko from https://127.0.0.1:5000 ...'
    $electron = Start-Process -FilePath $electronExecutable `
        -ArgumentList @(
            'app\electron\build',
            '--origin=https://127.0.0.1:5000',
            '--ignore-certificate-errors',
            '--remote-debugging-address=127.0.0.1',
            '--remote-debugging-port=9222'
        ) `
        -WorkingDirectory $PSScriptRoot `
        -RedirectStandardOutput $electronOutputLog `
        -RedirectStandardError $electronErrorLog `
        -PassThru
    @{ ServerPID = $server.Id; ElectronPID = $electron.Id } |
        ConvertTo-Json | Set-Content -LiteralPath $stateFile
    [void] (Show-HakuNekoWindow -ProcessID $electron.Id)
    Write-Host 'HakuNeko is running. Keep this terminal open; closing the app returns to the prompt.'
    $electron.WaitForExit()
} finally {
    if (-not $server.HasExited) {
        Stop-Process -Id $server.Id
        $server.WaitForExit()
    }
    Remove-Item -LiteralPath $stateFile -Force -ErrorAction SilentlyContinue
}
