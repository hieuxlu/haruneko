[CmdletBinding()]
param(
    [string] $ConfigPath,
    [string] $RootPath = (Get-Location).Path,
    [string] $OutputPath,
    [string] $AssetsRoot,
    [string[]] $Series,
    [Alias('Volume')] [int[]] $SelectedVolume,
    [switch] $AllowPartial,
    [switch] $Force,
    [switch] $ValidateOnly,
    [switch] $NoCoverDownload,
    [switch] $DownloadCovers,
    [string] $ReportPath,
    [string] $Python = 'python'
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path $RootPath 'volumes.json'
}
$cli = Join-Path $PSScriptRoot 'scripts/cbz/cbz.py'
$common = @('--config', $ConfigPath, '--root', $RootPath)
if ($OutputPath) { $common += @('--output', $OutputPath) }
if ($AssetsRoot) { $common += @('--assets-root', $AssetsRoot) }
if ($Series) { $common += @('--series') + $Series }
if ($null -ne $SelectedVolume -and $SelectedVolume.Count -gt 0) {
    $common += @('--volume') + @($SelectedVolume | ForEach-Object { [string] $_ })
}
if ($DownloadCovers -and -not $NoCoverDownload -and -not $ValidateOnly) {
    & $Python $cli covers @common
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
$command = if ($ValidateOnly) { 'plan' } else { 'build' }
$options = @()
if (-not $ValidateOnly) {
    if ($AllowPartial) { $options += '--allow-partial' }
    if ($Force) { $options += '--force' }
}
if ($ReportPath) { $options += @('--report', $ReportPath) }
& $Python $cli $command @common @options
exit $LASTEXITCODE
