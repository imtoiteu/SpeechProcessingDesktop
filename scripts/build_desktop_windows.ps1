# Build the STTLive desktop client (Tauri) on Windows.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_desktop_windows.ps1
#
# Requires Node/npm, Rust (MSVC toolchain), the MSVC C++ Build Tools and the
# WebView2 runtime — see docs/DESKTOP_APP.md. Tauri emits an .msi / .exe (NSIS)
# installer under desktop\src-tauri\target\release\bundle\.
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if (-not (Get-Command npm   -ErrorAction SilentlyContinue)) { throw "npm not found. Install Node.js." }
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) { throw "cargo/Rust not found. See https://rustup.rs" }

Push-Location desktop
npm install
npm run icon
npm run build
Pop-Location

$BundleDir = Join-Path $RepoRoot "desktop\src-tauri\target\release\bundle"
Write-Host ""
Write-Host "Build finished. Installers (if produced) are under:"
Write-Host "  $BundleDir"
Write-Host "Look for msi\ or nsis\ subfolders."
