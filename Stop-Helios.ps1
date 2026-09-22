$ErrorActionPreference = 'Stop'
$heliosPidFile = Join-Path $PSScriptRoot 'data\server-process.json'
if (-not (Test-Path -LiteralPath $heliosPidFile)) { Write-Host 'No Helios server process is registered.'; return }
$heliosSaved = Get-Content -LiteralPath $heliosPidFile | ConvertFrom-Json
$heliosProcess = Get-Process -Id $heliosSaved.pid -ErrorAction SilentlyContinue
if ($heliosProcess) {
    $heliosExpectedRoot = $PSScriptRoot.TrimEnd('\') + '\'
    $heliosSavedStart = [DateTimeOffset]$heliosSaved.started
    $heliosMatches = $heliosProcess.ProcessName -eq 'python' -and $heliosProcess.Path -and $heliosProcess.Path.StartsWith($heliosExpectedRoot, [StringComparison]::OrdinalIgnoreCase) -and $heliosProcess.StartTime.ToUniversalTime().Ticks -eq $heliosSavedStart.UtcDateTime.Ticks
    if (-not $heliosMatches) { throw 'The registered PID no longer matches this Helios server. No process was stopped.' }
    Stop-Process -Id $heliosProcess.Id
    Wait-Process -Id $heliosProcess.Id -Timeout 10 -ErrorAction SilentlyContinue
    Write-Host 'Helios stopped. Saved recordings remain in data.'
}
Remove-Item -LiteralPath $heliosPidFile
