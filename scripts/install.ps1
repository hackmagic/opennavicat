#!/usr/bin/env pwsh
# OpenNavicat Windows installer — downloads CLI binary or falls back to pip

$Repo = "opennavicat/opennavicat"
$InstallDir = if ($env:INSTALL_DIR) { $env:INSTALL_DIR } else { "$env:LOCALAPPDATA\Programs\OpenNavicat" }

# Detect arch
$Arch = switch ($env:PROCESSOR_ARCHITECTURE) {
  "AMD64" { "x86_64" }
  "ARM64" { "arm64" }
  default { Write-Error "Unsupported architecture: $env:PROCESSOR_ARCHITECTURE"; exit 1 }
}

Write-Host "Fetching latest release..."
$Release = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest"
$Asset = $Release.assets | Where-Object { $_.name -like "*win*$Arch*" -and $_.name -like "*.zip" } | Select-Object -First 1

if (-not $Asset) {
  Write-Host "No prebuilt binary found — falling back to pip install"
  pip install opennavicat
  exit 0
}

Write-Host "Downloading $($Asset.name)..."
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
$ZipPath = "$env:TEMP\opennavicat.zip"
Invoke-RestMethod -Uri $Asset.browser_download_url -OutFile $ZipPath
Expand-Archive -Path $ZipPath -DestinationPath $InstallDir -Force
Remove-Item $ZipPath

# Add to PATH (user-level)
$CurrentPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($CurrentPath -notlike "*$InstallDir*") {
  [Environment]::SetEnvironmentVariable("Path", "$CurrentPath;$InstallDir", "User")
}

Write-Host "Installed opennavicat to $InstallDir"
