#!/usr/bin/env bash
# Launch the WhisperLiveKit STT server on :8000 for LINUX.
#
# macOS uses the `mlx-whisper` (Metal) backend, which does NOT exist on Linux.
# This script therefore defaults to `faster-whisper` — the cross-platform backend
# that WhisperLiveKit's own CLI auto-selects on non-Apple hosts (CPU by default,
# or CUDA if a GPU build of faster-whisper / ctranslate2 is installed). It is the
# upstream-supported Linux path, but real accuracy/speed on Linux must be verified
# on an actual Linux machine (it cannot be validated on the macOS dev box).
#
# Like the macOS script, this only `exec`s the existing `whisperlivekit-server`
# CLI — it does not rewrite the STT engine — so killing this process kills the
# real server (no orphaned uvicorn).
#
# Usage:
#   ./scripts/run_stt_linux.sh
#
# Environment (all optional):
#   STT_PYTHON=/path/to/python   # run `python -m whisperlivekit.basic_server` instead
#   STT_MODEL=large-v3-turbo     STT_BACKEND=faster-whisper
#   STT_BACKEND_POLICY=simulstreaming   # or 'localagreement' if simulstreaming misbehaves
#   STT_LANGUAGE=auto            STT_HOST=localhost   STT_PORT=8000
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Resolve the server: explicit interpreter, then the project .venv, then PATH.
if [[ -n "${STT_PYTHON:-}" ]]; then
  SERVER=("$STT_PYTHON" -m whisperlivekit.basic_server)
elif [[ -x ".venv/bin/whisperlivekit-server" ]]; then
  SERVER=(".venv/bin/whisperlivekit-server")
elif command -v whisperlivekit-server >/dev/null 2>&1; then
  SERVER=("whisperlivekit-server")
else
  echo "ERROR: whisperlivekit-server not found." >&2
  echo "  Set up the STT venv (Linux):" >&2
  echo "    uv venv --python 3.12 .venv" >&2
  echo "    uv pip install --python .venv -e ./WhisperLiveKit" >&2
  echo "    uv pip install --python .venv faster-whisper   # CPU; add CUDA build for GPU" >&2
  echo "  ...or point STT_PYTHON at an interpreter that has whisperlivekit." >&2
  exit 1
fi

# Preflight the required Silero VAD ONNX asset (committed in the repo; restored if
# missing) so STT does not die at startup with "Model file not found: silero_vad.onnx".
# shellcheck source=scripts/_ensure_vad.sh
source "$REPO_ROOT/scripts/_ensure_vad.sh"
if ! ensure_vad_onnx; then
  echo "ERROR: required Silero VAD asset missing: $(vad_onnx_path)" >&2
  echo "  Copy silero_vad.onnx into WhisperLiveKit/whisperlivekit/silero_vad_models/." >&2
  exit 1
fi

MODEL="${STT_MODEL:-large-v3-turbo}"
BACKEND="${STT_BACKEND:-faster-whisper}"
POLICY="${STT_BACKEND_POLICY:-simulstreaming}"
LANG="${STT_LANGUAGE:-auto}"
HOST="${STT_HOST:-localhost}"
PORT="${STT_PORT:-8000}"

echo "Starting WhisperLiveKit STT on ${HOST}:${PORT} (model=${MODEL}, backend=${BACKEND}) [Linux]"
exec "${SERVER[@]}" \
  --model "$MODEL" \
  --backend "$BACKEND" \
  --backend-policy "$POLICY" \
  --language "$LANG" \
  --host "$HOST" --port "$PORT"
