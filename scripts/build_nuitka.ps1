#!/usr/bin/env pwsh
<#
.SYNOPSIS
Build OpenNavicat CLI/GUI with Nuitka (AOT compiler).
Produces standalone single-file executables in dist/nuitka/.
#>
param(
    [ValidateSet("cli", "gui")]
    [string]$Target = "cli"
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot/.."
$src = "$root/open_navicat"
$outDir = "$root/dist/nuitka"
$outName = if ($Target -eq "gui") { "opennavicat" } else { "opennavicat-cli" }
$entry = if ($Target -eq "gui") { "gui_main.py" } else { "cli_main.py" }
$icon = if ($Target -eq "gui" -and (Test-Path "$src/ui/resources/icon.ico")) {
    "--windows-icon-from-ico=$src/ui/resources/icon.ico"
} else { "" }

Write-Host "Building OpenNavicat ($Target) with Nuitka..." -ForegroundColor Cyan

nuitka --onefile --standalone `
    --python-flag=-m `
    --enable-plugin=pyside6 `
    $icon `
    --output-dir="$outDir" `
    --output-name="$outName" `
    --include-data-dir="$src/i18n=open_navicat/i18n" `
    --include-package=open_navicat `
    --disable-ccache `
    --noinclude-pytest-mode=nofollow `
    --noinclude-setuptools-mode=nofollow `
    "$src/$entry"

Write-Host "Done: $outDir/$outName" -ForegroundColor Green
