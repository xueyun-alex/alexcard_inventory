$ErrorActionPreference = "Stop"

$Version = if ($args.Count -ge 1) { $args[0] } else { "1.1.3" }

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Error "Virtual environment not found. Run: py -3.11 -m venv .venv && .venv\Scripts\pip install -r requirements.txt -r requirements-build.txt"
}

& $Python -m pip install -r requirements-build.txt
& $Python -m PyInstaller --noconfirm AlexcardInventory.spec

$DistDir = Join-Path $Root "dist\AlexcardInventory"
if (-not (Test-Path (Join-Path $DistDir "AlexcardInventory.exe"))) {
    Write-Error "Build failed: AlexcardInventory.exe not found in $DistDir"
}

$VersionDir = Join-Path $Root "dist\$Version\AlexcardInventory"
if (Test-Path (Join-Path $Root "dist\$Version")) {
    Remove-Item (Join-Path $Root "dist\$Version") -Recurse -Force
}
New-Item -ItemType Directory -Path (Split-Path -Parent $VersionDir) -Force | Out-Null
Copy-Item $DistDir $VersionDir -Recurse
Set-Content -Path (Join-Path $VersionDir "VERSION") -Value $Version -NoNewline -Encoding ascii

Write-Host ""
Write-Host "Build complete: $VersionDir\AlexcardInventory.exe"
Write-Host "Version: $Version"
Write-Host "Copy the whole AlexcardInventory folder when distributing."
