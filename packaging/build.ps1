# Build bản cài đặt Windows: PyInstaller (thư mục) -> Inno Setup (ClipVault-Setup-<version>.exe trong dist\).
# Chạy từ thư mục gốc dự án:  powershell -ExecutionPolicy Bypass -File packaging\build.ps1
# Yêu cầu: .venv có pyinstaller (pip install -e ".[build]") và Inno Setup 6 (ISCC.exe).
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$py = ".venv\Scripts\python.exe"

$version = (& $py packaging\make_version_info.py).Trim()
Write-Host "ClipVault $version"

Remove-Item -Recurse -Force build, dist\ClipVault -ErrorAction SilentlyContinue
& $py -m PyInstaller packaging\clipvault.spec --noconfirm --distpath dist --workpath build
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$candidates = @(
  "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
  "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
  "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)
$iscc = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 (ISCC.exe) not found" }
& $iscc "/DAppVersion=$version" packaging\installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Write-Host "Done: dist\ClipVault-Setup-$version.exe"
