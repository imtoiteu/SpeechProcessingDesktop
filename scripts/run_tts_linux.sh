#!/usr/bin/env bash
# Launch the VieNeu-TTS sidecar on :8011 for LINUX.
#
# Same server as macOS (`python -m tts.server`); the only difference is the
# llama-cpp-python wheel. macOS uses the Metal wheel; Linux has no Metal, so the
# GGUF backbone runs via a CPU wheel (or a CUDA wheel if you have an NVIDIA GPU).
# TTS is torch-free (llama.cpp + ONNX codec), so CPU is the safe default. Linux
# TTS is STRUCTURALLY prepared but PENDING VALIDATION on a real Linux machine.
#
# Usage:
#   ./scripts/run_tts_linux.sh
#
# Environment (all optional, see src/tts/config.py):
#   TTS_BACKBONE=pnnbao-ump/VieNeu-TTS-0.3B-q8-gguf   TTS_CODEC=...
#   TTS_DEVICE=cpu        TTS_PORT=8011               TTS_EAGER_LOAD=1
#   TTS_VENV=VieNeu-TTS/.venv   TTS_PYTHON=/path/to/python
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ -n "${TTS_PYTHON:-}" ]]; then
  PY="$TTS_PYTHON"
else
  VENV="${TTS_VENV:-VieNeu-TTS/.venv}"
  PY="$VENV/bin/python"
fi

if [[ ! -x "$PY" ]]; then
  echo "TTS interpreter not found at: $PY" >&2
  echo "Set up the VieNeu-TTS venv once:  cd VieNeu-TTS && uv sync" >&2
  echo "(then add llama-cpp-python + trafilatura — see the preflight notes below)." >&2
  exit 1
fi

# --- dependency preflight (Linux) -----------------------------------------
# A plain `uv sync` installs the torch-free CORE but NOT llama-cpp-python or
# trafilatura. On Linux install the CPU wheel (or a CUDA wheel for GPU):
#
#   uv pip install --python VieNeu-TTS/.venv "llama-cpp-python==0.3.16" \
#       --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu/ \
#       --index-strategy unsafe-best-match
#   uv pip install --python VieNeu-TTS/.venv "trafilatura>=2.0.0"
#
if ! "$PY" -c "import vieneu" >/dev/null 2>&1; then
  echo "ERROR: 'vieneu' not importable in $PY." >&2
  echo "  cd VieNeu-TTS && uv sync" >&2
  exit 1
fi
if ! "$PY" -c "import llama_cpp" >/dev/null 2>&1; then
  echo "ERROR: 'llama_cpp' missing (a plain 'uv sync' prunes it). Install it (Linux CPU wheel):" >&2
  echo "  uv pip install --python \"$PY\" \"llama-cpp-python==0.3.16\" \\" >&2
  echo "      --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu/ \\" >&2
  echo "      --index-strategy unsafe-best-match" >&2
  exit 1
fi
if ! "$PY" -c "import trafilatura" >/dev/null 2>&1; then
  echo "WARNING: 'trafilatura' missing — URL extraction will be disabled." >&2
  echo "  uv pip install --python \"$PY\" \"trafilatura>=2.0.0\"" >&2
fi

export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PY" -m tts.server
