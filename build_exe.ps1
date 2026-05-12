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

$ReleaseName = "SHTUClaudeProxy-v$Version"
$OneFileName = "$ReleaseName-windows-x64"
$OneDirZip = "$Root\release\$OneFileName.zip"
$SourceZip = "$Root\release\$ReleaseName-source-linux-macos.zip"
$ReleaseReadme = "$Root\release\README-release-v$Version.txt"
$Checksums = "$Root\release\SHA256SUMS.txt"

if (-not $OneFileOnly) {
  python -m PyInstaller `
    --noconfirm `
    --clean `
    --name SHTUClaudeProxy `
    --windowed `
    --add-data "proxy.py;." `
    --add-data "config_store.py;." `
    --add-data "safe_io.py;." `
    app.py

  Compress-Archive `
    -Path "$Root\dist\SHTUClaudeProxy\*" `
    -DestinationPath $OneDirZip `
    -Force

  Write-Host ""
  Write-Host "Folder build complete: $Root\dist\SHTUClaudeProxy\SHTUClaudeProxy.exe"
  Write-Host "Zip package complete: $OneDirZip"
}

if (-not $OneDirOnly) {
  python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name $OneFileName `
    --windowed `
    --add-data "proxy.py;." `
    --add-data "config_store.py;." `
    --add-data "safe_io.py;." `
    app.py

  Copy-Item `
    "$Root\dist\$OneFileName.exe" `
    "$Root\release\$OneFileName.exe" `
    -Force

  Write-Host ""
  Write-Host "Single-file build complete: $Root\release\$OneFileName.exe"
}

if (-not $OneDirOnly -and -not $OneFileOnly) {
  $SourceStageRoot = "$Root\build\source-package"
  $SourceStage = "$SourceStageRoot\$ReleaseName-source"
  if (Test-Path $SourceStageRoot) {
    Remove-Item $SourceStageRoot -Recurse -Force
  }
  New-Item -ItemType Directory -Force $SourceStage | Out-Null

  $TrackedFiles = git -C $Root ls-files
  foreach ($RelativePath in $TrackedFiles) {
    if ($RelativePath -match '^(release|build|dist)/') { continue }
    if ($RelativePath -match '(^|/)(config\.json|\.env|auth\.json)$') { continue }
    if ($RelativePath -match '\.(bak|key|pem)$') { continue }

    $SourcePath = Join-Path $Root $RelativePath
    $DestPath = Join-Path $SourceStage $RelativePath
    $DestDir = Split-Path -Parent $DestPath
    New-Item -ItemType Directory -Force $DestDir | Out-Null
    Copy-Item $SourcePath $DestPath -Force
  }

  Compress-Archive `
    -Path $SourceStage `
    -DestinationPath $SourceZip `
    -Force

  @(
    "SHTUClaudeProxy v$Version release assets",
    "",
    "Recommended Windows package:",
    "- $OneFileName.exe",
    "",
    "Portable Windows folder package:",
    "- $OneFileName.zip",
    "",
    "Linux/macOS source package:",
    "- $ReleaseName-source-linux-macos.zip",
    "",
    "Integrity checks:",
    "- SHA256SUMS.txt",
    "",
    "This release package excludes local config files, API keys, backups, probe outputs, and build directories."
  ) | Set-Content -Path $ReleaseReadme -Encoding UTF8

  $ChecksumFiles = @(
    "$Root\release\$OneFileName.exe",
    $OneDirZip,
    $SourceZip,
    $ReleaseReadme
  )
  $ChecksumLines = foreach ($File in $ChecksumFiles) {
    $Hash = Get-FileHash -Algorithm SHA256 $File
    "$($Hash.Hash.ToLowerInvariant())  $(Split-Path -Leaf $File)"
  }
  $ChecksumLines | Set-Content -Path $Checksums -Encoding ASCII

  Write-Host ""
  Write-Host "Source package complete: $SourceZip"
  Write-Host "Release README complete: $ReleaseReadme"
  Write-Host "Checksums complete: $Checksums"
}

Write-Host ""
Write-Host "Build complete. Release files are in: $Root\release"
