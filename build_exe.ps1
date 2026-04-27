param(
  [switch]$InstallDeps
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if ($InstallDeps) {
  python -m pip install --upgrade pip
  python -m pip install pyinstaller
}

python -m PyInstaller `
  --noconfirm `
  --clean `
  --name SHTUClaudeProxy `
  --windowed `
  --add-data "proxy.py;." `
  --add-data "config_store.py;." `
  app.py

Write-Host ""
Write-Host "Build complete: $Root\dist\SHTUClaudeProxy\SHTUClaudeProxy.exe"
Write-Host "Run it, configure models, then click Start Proxy."

