$ErrorActionPreference = "Stop"

$Version = if ($args.Count -ge 1) { $args[0] } else { "1.1.3" }

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Error "Virtual environment not found. Run: py -3.11 -m venv .venv && .venv\Scripts\pip install -r requirements.txt -r requirements-build.txt"
}

$VersionRoot = Join-Path $Root "dist\$Version"
$VersionDir = Join-Path $VersionRoot "AlexcardInventory"
if (Test-Path $VersionRoot) {
    Remove-Item $VersionRoot -Recurse -Force
}

& $Python -m pip install -r requirements-build.txt
& $Python -m PyInstaller --noconfirm --distpath $VersionRoot AlexcardInventory.spec

if (-not (Test-Path (Join-Path $VersionDir "AlexcardInventory.exe"))) {
    Write-Error "Build failed: AlexcardInventory.exe not found in $VersionDir"
}

Set-Content -Path (Join-Path $VersionDir "VERSION") -Value $Version -NoNewline -Encoding ascii

Write-Host ""
Write-Host "Build complete: $VersionDir\AlexcardInventory.exe"
Write-Host "Version: $Version"
Write-Host "Copy the whole AlexcardInventory folder when distributing."
