# Setup for Windows. IMPORTANT — read this before assuming parity with macOS:
#
#   * The DESKTOP CLIENT (Tauri app) builds and runs on Windows (needs the
#     Microsoft C++ Build Tools + WebView2 runtime; see docs/DESKTOP_APP.md).
#   * The LOCAL STT BACKEND on Windows uses `faster-whisper` (CPU, or CUDA with a
#     GPU ctranslate2 build). Upstream-supported but NOT validated by this project.
#   * There is NO MLX/Metal on Windows. Do not expect Apple-Silicon performance.
#   * The LOCAL TTS BACKEND needs a CPU or CUDA build of llama-cpp-python (NOT the
#     macOS Metal wheel). Unvalidated here.
#   * RECOMMENDED on Windows: run the desktop app in **Remote Server Mode** against
#     a validated STT/TTS host (e.g. a Mac) on your LAN.
#
# Usage (from the repo root):
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\bootstrap_windows.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\bootstrap_windows.ps1 -WithStt
param(
    [switch]$WithStt
)
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Warn($m) { Write-Host "WARNING: $m" -ForegroundColor Yellow }
function Have($c) { return [bool](Get-Command $c -ErrorAction SilentlyContinue) }

Write-Host "==> Checking prerequisites" -ForegroundColor Cyan
if (-not (Have node))   { Warn "node missing (needed for the desktop app). https://nodejs.org" }
if (-not (Have npm))    { Warn "npm missing (needed for the desktop app)." }
if (-not (Have cargo))  { Warn "cargo/Rust missing (needed for the desktop app). https://rustup.rs" }
if (-not (Have ffmpeg)) { Warn "ffmpeg missing (needed for file/video decode). https://ffmpeg.org" }
Warn "Tauri on Windows needs the MSVC C++ Build Tools and the WebView2 runtime. See docs/DESKTOP_APP.md."

Write-Host "==> Installing desktop app deps (npm) + generating icons" -ForegroundColor Cyan
if (Have npm) {
    Push-Location desktop
    npm install
    npm run icon
    Pop-Location
    Write-Host "OK: desktop npm deps + icons"
} else {
    Warn "Skipping desktop deps (npm missing)."
}

if ($WithStt) {
    Write-Host "==> Creating a LOCAL faster-whisper STT venv (UNVALIDATED on Windows)" -ForegroundColor Cyan
    if (-not (Have uv)) { throw "uv required for -WithStt. See https://astral.sh/uv" }
    uv venv --python 3.12 .venv
    uv pip install --python .venv -e ./WhisperLiveKit
    # faster-whisper is the cross-platform CPU backend. For CUDA install a GPU
    # ctranslate2 build yourself (see faster-whisper docs) — not done automatically.
    uv pip install --python .venv faster-whisper
    Write-Host "OK: .venv (faster-whisper). Start it with scripts\run_stt_windows.ps1"
    Warn "Local STT on Windows is unvalidated by this project — verify before relying on it."
    Write-Host "Local TTS on Windows: install a CPU/CUDA llama-cpp-python wheel into VieNeu-TTS\.venv (NOT the macOS Metal wheel). Unvalidated here."
}

Write-Host ""
Write-Host "==> Windows bootstrap complete." -ForegroundColor Green
Write-Host "Build the desktop client:"
Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_desktop_windows.ps1"
Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\open_desktop_windows.ps1"
Write-Host "Recommended runtime: launch the app and choose Remote Server Mode against a validated host."
