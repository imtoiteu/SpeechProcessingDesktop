# Launch the WhisperLiveKit STT server on :8000 for WINDOWS.
#
# Windows has no MLX / Metal, so the macOS `mlx-whisper` backend does not apply.
# This script defaults to `faster-whisper` — the cross-platform backend that
# WhisperLiveKit's own CLI auto-selects on non-Apple hosts (CPU by default, or
# CUDA if a GPU build of faster-whisper / ctranslate2 is installed). This is the
# upstream-supported Windows path, but real accuracy/speed on Windows must be
# verified on an actual Windows machine (it cannot be validated on the macOS dev box).
#
# It only invokes the existing `whisperlivekit-server` CLI — it does not rewrite
# the STT engine.
#
# Usage (from the repo root):
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_stt_windows.ps1
#
# Environment (all optional):
#   STT_PYTHON=C:\path\to\python.exe   # run `python -m whisperlivekit.basic_server` instead
#   STT_MODEL=large-v3-turbo           STT_BACKEND=faster-whisper
#   STT_BACKEND_POLICY=simulstreaming  # or 'localagreement' if simulstreaming misbehaves
#   STT_LANGUAGE=auto                  STT_HOST=localhost   STT_PORT=8000
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

# Resolve the server: explicit interpreter, then the project .venv, then PATH.
$ServerArgs = @()
if ($env:STT_PYTHON) {
    $Exe = $env:STT_PYTHON
    $ServerArgs += @("-m", "whisperlivekit.basic_server")
} elseif (Test-Path ".venv\Scripts\whisperlivekit-server.exe") {
    $Exe = ".venv\Scripts\whisperlivekit-server.exe"
} elseif (Get-Command whisperlivekit-server -ErrorAction SilentlyContinue) {
    $Exe = "whisperlivekit-server"
} else {
    Write-Error @"
whisperlivekit-server not found. Set up the STT venv (Windows):
    uv venv --python 3.12 .venv
    uv pip install --python .venv -e .\WhisperLiveKit
    uv pip install --python .venv faster-whisper   # CPU; add a CUDA build for GPU
...or point STT_PYTHON at an interpreter that has whisperlivekit.
"@
    exit 1
}

# Preflight the required Silero VAD ONNX asset (committed in the repo; restored from
# the pinned upstream tag if missing) so STT doesn't die with "Model file not found".
$VadOnnx = Join-Path $RepoRoot "WhisperLiveKit\whisperlivekit\silero_vad_models\silero_vad.onnx"
if (-not ((Test-Path $VadOnnx) -and ((Get-Item $VadOnnx).Length -ge 1000000))) {
    Write-Host "Silero VAD ONNX missing at $VadOnnx — attempting restore..."
    $VadUrl = "https://raw.githubusercontent.com/QuentinFuxa/WhisperLiveKit/v0.2.22/whisperlivekit/silero_vad_models/silero_vad.onnx"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $VadOnnx) | Out-Null
    try {
        Invoke-WebRequest -Uri $VadUrl -OutFile $VadOnnx -UseBasicParsing -TimeoutSec 60
    } catch { }
    if (-not ((Test-Path $VadOnnx) -and ((Get-Item $VadOnnx).Length -ge 1000000))) {
        Write-Error "Required Silero VAD asset missing: $VadOnnx`nCopy silero_vad.onnx into WhisperLiveKit\whisperlivekit\silero_vad_models\."
        exit 1
    }
    Write-Host "Restored Silero VAD ONNX -> $VadOnnx"
}

$Model   = if ($env:STT_MODEL)          { $env:STT_MODEL }          else { "large-v3-turbo" }
$Backend = if ($env:STT_BACKEND)        { $env:STT_BACKEND }        else { "faster-whisper" }
$Policy  = if ($env:STT_BACKEND_POLICY) { $env:STT_BACKEND_POLICY } else { "simulstreaming" }
$Lang    = if ($env:STT_LANGUAGE)       { $env:STT_LANGUAGE }       else { "auto" }
$AppHost = if ($env:STT_HOST)           { $env:STT_HOST }           else { "localhost" }
$Port    = if ($env:STT_PORT)           { $env:STT_PORT }           else { "8000" }

$ServerArgs += @(
    "--model", $Model,
    "--backend", $Backend,
    "--backend-policy", $Policy,
    "--language", $Lang,
    "--host", $AppHost, "--port", $Port
)

Write-Host "Starting WhisperLiveKit STT on ${AppHost}:${Port} (model=$Model, backend=$Backend) [Windows]"
& $Exe @ServerArgs
