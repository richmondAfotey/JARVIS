# Builds JARVIS AI into a standalone Windows executable (Phase 19).
#
# Usage:  powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1
#
# Output: .\dist\JARVIS AI.exe

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "==> Creating virtual environment..."
    python -m venv .venv
}

Write-Host "==> Installing dependencies..."
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt -r requirements-dev.txt

Write-Host "==> Building executable..."
& ".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean jarvis.spec

Write-Host ""
Write-Host "Done! Executable: .\dist\JARVIS AI.exe"
Write-Host "Place a filled-out .env file next to it to enable online features."