$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Error "Virtual environment not found. Run: py -3.11 -m venv .venv && .venv\Scripts\pip install -r requirements.txt -r requirements-build.txt"
}

& $Python -m pip install -r requirements-build.txt
& $Python -m PyInstaller --noconfirm AlexcardInventory.spec

$DistDir = Join-Path $Root "dist\AlexcardInventory"
Write-Host ""
Write-Host "Build complete: $DistDir\AlexcardInventory.exe"
Write-Host "Copy the whole AlexcardInventory folder when distributing."
