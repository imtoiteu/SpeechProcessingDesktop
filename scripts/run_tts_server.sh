#!/usr/bin/env bash
# Launch the VieNeu-TTS sidecar (separate process & venv from STT).
#
# Usage:
#   ./scripts/run_tts_server.sh
#
# By default it runs in the VieNeu-TTS virtual environment (which already has the
# `vieneu` SDK, llama.cpp and the ONNX codec installed) so nothing TTS-related
# touches the STT `.venv`. Override the interpreter with TTS_VENV or TTS_PYTHON.
#
# Environment (all optional, see src/tts/config.py):
#   TTS_BACKBONE=pnnbao-ump/VieNeu-TTS-0.3B-q8-gguf   TTS_CODEC=...
#   TTS_DEVICE=cpu        TTS_PORT=8011               TTS_EAGER_LOAD=1
#   TTS_TEMPERATURE=0.7   TTS_DATA_DIR=tts-data
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Prefer an explicit interpreter, else the VieNeu venv, else a local .venv-tts.
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

# --- dependency preflight -------------------------------------------------
# A plain `uv sync` installs the torch-free CORE but NOT llama-cpp-python or
# trafilatura (they live only in the heavy `gpu` group). The GGUF backbone needs
# llama_cpp; URL extraction needs trafilatura. Install them into the venv with:
#
#   uv pip install --python VieNeu-TTS/.venv "llama-cpp-python==0.3.16" \
#       --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/metal/ \
#       --index-strategy unsafe-best-match
#   uv pip install --python VieNeu-TTS/.venv "trafilatura>=2.0.0"
#
if ! "$PY" -c "import vieneu" >/dev/null 2>&1; then
  echo "ERROR: 'vieneu' not importable in $PY." >&2
  echo "  cd VieNeu-TTS && uv sync" >&2
  exit 1
fi
if ! "$PY" -c "import llama_cpp" >/dev/null 2>&1; then
  echo "ERROR: 'llama_cpp' missing (a plain 'uv sync' prunes it). Install it:" >&2
  echo "  uv pip install --python \"$PY\" \"llama-cpp-python==0.3.16\" \\" >&2
  echo "      --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/metal/ \\" >&2
  echo "      --index-strategy unsafe-best-match" >&2
  exit 1
fi
if ! "$PY" -c "import trafilatura" >/dev/null 2>&1; then
  echo "WARNING: 'trafilatura' missing — URL extraction will be disabled." >&2
  echo "  uv pip install --python \"$PY\" \"trafilatura>=2.0.0\"" >&2
fi

# `tts` package lives under src/; `vieneu`/`vieneu_utils` are installed in the venv.
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PY" -m tts.server
