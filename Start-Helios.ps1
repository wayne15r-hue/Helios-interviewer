param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$heliosPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $heliosPython) -or -not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'dist\index.html'))) { & (Join-Path $PSScriptRoot 'Setup-Helios.ps1') }
$heliosSha = [System.Security.Cryptography.SHA256]::Create()
$heliosHash = $heliosSha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($PSScriptRoot.ToLowerInvariant()))
$heliosInstance = ([BitConverter]::ToString($heliosHash)).Replace('-', '').ToLowerInvariant().Substring(0,16)
$heliosSha.Dispose()
function Read-HeliosHealth {
    $heliosRequest = [System.Net.WebRequest]::Create('http://127.0.0.1:8765/api/health')
    $heliosRequest.Proxy = $null
    $heliosRequest.Timeout = 2000
    try {
        $heliosResponse = $heliosRequest.GetResponse()
        try {
            $heliosReader = New-Object System.IO.StreamReader($heliosResponse.GetResponseStream())
            try { return ($heliosReader.ReadToEnd() | ConvertFrom-Json) } finally { $heliosReader.Dispose() }
        } finally { $heliosResponse.Dispose() }
    } catch { return $null }
}
$heliosMutex = New-Object System.Threading.Mutex($false, "Local\Helios-$heliosInstance")
$heliosOwnsMutex = $false
try {
    $heliosOwnsMutex = $heliosMutex.WaitOne(30000)
    if (-not $heliosOwnsMutex) { throw 'Another Helios launcher is still starting. Please try again shortly.' }
    $heliosHealth = Read-HeliosHealth
    if ($heliosHealth -and $heliosHealth.name -ne 'Helios') { throw 'Another application is using port 8765.' }
    if ($heliosHealth.instance -and $heliosHealth.instance -ne $heliosInstance) { throw 'A different Helios installation is using port 8765.' }
    $heliosData = Join-Path $PSScriptRoot 'data'
    New-Item -ItemType Directory -Path $heliosData -Force | Out-Null
    if (-not $heliosHealth) {
        $env:MPLCONFIGDIR = Join-Path $heliosData 'cache\matplotlib'
        $env:HF_HUB_DISABLE_TELEMETRY = '1'
        $env:PYANNOTE_METRICS_ENABLED = '0'
        $heliosLogId = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
        $heliosErrorLog = Join-Path $heliosData "server-$heliosLogId-error.log"
        $heliosProcess = Start-Process -FilePath $heliosPython -ArgumentList @('-m','uvicorn','server.app:app','--host','127.0.0.1','--port','8765','--ws-max-size','33554432','--no-access-log') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $heliosData "server-$heliosLogId.log") -RedirectStandardError $heliosErrorLog
        for ($heliosAttempt = 0; $heliosAttempt -lt 30; $heliosAttempt++) {
            Start-Sleep -Milliseconds 500
            $heliosHealth = Read-HeliosHealth
            if ($heliosHealth -and $heliosHealth.instance -eq $heliosInstance) { break }
            if ($heliosProcess.HasExited) { break }
        }
        if (-not $heliosHealth -or $heliosHealth.instance -ne $heliosInstance) { throw "Helios did not start. See $heliosErrorLog" }
    }
    if ($heliosHealth.pid) {
        $heliosServer = Get-Process -Id $heliosHealth.pid -ErrorAction Stop
        @{ pid=$heliosServer.Id; started=$heliosServer.StartTime.ToUniversalTime().ToString('o'); instance=$heliosInstance } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $heliosData 'server-process.json')
    }
} finally {
    if ($heliosOwnsMutex) { $heliosMutex.ReleaseMutex() }
    $heliosMutex.Dispose()
}
if (-not $NoBrowser) { Start-Process 'http://localhost:8765' }
Write-Host 'Helios is running at http://localhost:8765'
