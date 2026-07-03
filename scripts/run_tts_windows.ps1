# Launch the VieNeu-TTS sidecar on :8011 for WINDOWS.
#
# Same server as macOS (`python -m tts.server`); the difference is the
# llama-cpp-python wheel. macOS uses the Metal wheel; Windows has no Metal, so the
# GGUF backbone runs via a CPU wheel (or a CUDA wheel for an NVIDIA GPU). TTS is
# torch-free (llama.cpp + ONNX codec), so CPU is the safe default. Windows TTS is
# STRUCTURALLY prepared but PENDING VALIDATION on a real Windows machine.
#
# Usage (from the repo root):
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_tts_windows.ps1
#
# Environment (all optional, see src/tts/config.py):
#   TTS_BACKBONE=pnnbao-ump/VieNeu-TTS-0.3B-q8-gguf   TTS_CODEC=...
#   TTS_DEVICE=cpu        TTS_PORT=8011               TTS_EAGER_LOAD=1
#   TTS_VENV=VieNeu-TTS\.venv   TTS_PYTHON=C:\path\to\python.exe
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if ($env:TTS_PYTHON) {
    $Py = $env:TTS_PYTHON
} else {
    $Venv = if ($env:TTS_VENV) { $env:TTS_VENV } else { "VieNeu-TTS\.venv" }
    $Py = Join-Path $Venv "Scripts\python.exe"
}

if (-not (Test-Path $Py)) {
    Write-Error "TTS interpreter not found at: $Py`nSet up the VieNeu-TTS venv once:  cd VieNeu-TTS; uv sync"
    exit 1
}

# --- dependency preflight (Windows) ---------------------------------------
# A plain `uv sync` installs the torch-free CORE but NOT llama-cpp-python or
# trafilatura. On Windows install the CPU wheel (or a CUDA wheel for GPU):
#
#   uv pip install --python VieNeu-TTS\.venv "llama-cpp-python==0.3.16" `
#       --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu/ `
#       --index-strategy unsafe-best-match
#   uv pip install --python VieNeu-TTS\.venv "trafilatura>=2.0.0"
#
& $Py -c "import vieneu" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Error "'vieneu' not importable in $Py.`n  cd VieNeu-TTS; uv sync"
    exit 1
}
& $Py -c "import llama_cpp" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Error @"
'llama_cpp' missing (a plain 'uv sync' prunes it). Install it (Windows CPU wheel):
  uv pip install --python "$Py" "llama-cpp-python==0.3.16" ``
      --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu/ ``
      --index-strategy unsafe-best-match
"@
    exit 1
}
& $Py -c "import trafilatura" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Warning "'trafilatura' missing - URL extraction will be disabled.  uv pip install --python `"$Py`" `"trafilatura>=2.0.0`""
}

$env:PYTHONPATH = "$RepoRoot\src;$env:PYTHONPATH"
& $Py -m tts.server
