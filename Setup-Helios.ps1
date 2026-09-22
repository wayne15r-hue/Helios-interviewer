param([switch]$WithoutSpeakerSeparation)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:UV_CACHE_DIR = Join-Path $PSScriptRoot '.cache\uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $PSScriptRoot '.runtime\python'
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw 'Install Node.js 22 or newer, then run Setup-Helios.ps1 again.' }
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Install uv from https://docs.astral.sh/uv/getting-started/installation/ then run setup again.' }
Write-Host 'Installing the local Python application...'
if ($WithoutSpeakerSeparation) { uv sync --frozen --python 3.11 } else { uv sync --frozen --python 3.11 --extra speakers }
if ($LASTEXITCODE -ne 0) { throw 'Python setup failed. Check the output above and retry.' }
Write-Host 'Installing and building the dashboard...'
npm ci --no-audit --no-fund --cache .cache/npm
if ($LASTEXITCODE -ne 0) { throw 'Frontend installation failed.' }
npm run build
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
Write-Host 'Helios is ready to launch. Run Start-Helios.cmd.'
Write-Host 'Models are downloaded only when you choose Download in Settings.'
