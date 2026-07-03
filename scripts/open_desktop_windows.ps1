# Launch the STTLive desktop client on Windows.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\open_desktop_windows.ps1
#
# Runs the raw release .exe (works without installing the bundle).
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Exe = Join-Path $RepoRoot "desktop\src-tauri\target\release\STTLive.exe"

if (Test-Path $Exe) {
    Write-Host "Launching $Exe"
    Start-Process $Exe
} else {
    Write-Host "STTLive.exe not found at:" -ForegroundColor Red
    Write-Host "  $Exe"
    Write-Host "Please run scripts\build_desktop_windows.ps1 first (or install the produced .msi/.exe)."
    exit 1
}
