param(
  [switch]$InstallDeps,
  [switch]$OneDirOnly,
  [switch]$OneFileOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Version = (Get-Content "$Root\VERSION" -Raw -ErrorAction SilentlyContinue).Trim()
if (-not $Version) {
  $Version = "dev"
}

if ($InstallDeps) {
  python -m pip install --upgrade pip
  python -m pip install pyinstaller
}

New-Item -ItemType Directory -Force "$Root\release" | Out-Null

if (-not $OneFileOnly) {
  python -m PyInstaller `
    --noconfirm `
    --clean `
    --name SHTUClaudeProxy `
    --windowed `
    --add-data "proxy.py;." `
    --add-data "config_store.py;." `
    app.py

  Compress-Archive `
    -Path "$Root\dist\SHTUClaudeProxy\*" `
    -DestinationPath "$Root\release\SHTUClaudeProxy-windows-x64.zip" `
    -Force

  Write-Host ""
  Write-Host "Folder build complete: $Root\dist\SHTUClaudeProxy\SHTUClaudeProxy.exe"
  Write-Host "Zip package complete: $Root\release\SHTUClaudeProxy-windows-x64.zip"
}

if (-not $OneDirOnly) {
  $OneFileName = "SHTUClaudeProxy-v$Version-windows-x64"
  python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name $OneFileName `
    --windowed `
    --add-data "proxy.py;." `
    --add-data "config_store.py;." `
    app.py

  Copy-Item `
    "$Root\dist\$OneFileName.exe" `
    "$Root\release\$OneFileName.exe" `
    -Force

  Write-Host ""
  Write-Host "Single-file build complete: $Root\release\$OneFileName.exe"
}

Write-Host ""
Write-Host "Build complete. Release files are in: $Root\release"
