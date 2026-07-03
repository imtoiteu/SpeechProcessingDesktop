#!/usr/bin/env bash
# Launch the WhisperLiveKit STT server (streaming + batch ASR) on :8000.
#
# This is the exact command from run.md, wrapped so the desktop app (and Mac
# devs) can start STT reliably. It does NOT rewrite the STT engine — it only
# `exec`s the existing `whisperlivekit-server` CLI, so killing this process
# kills the real server (no orphaned uvicorn).
#
# Usage:
#   ./scripts/run_stt_server.sh
#
# Environment (all optional):
#   STTLIVE_STT_MODEL=large-v3-turbo   STTLIVE_STT_LANGUAGE=auto
#   STTLIVE_STT_HOST=localhost         STTLIVE_STT_PORT=8000
#   STT_PYTHON=/path/to/python         # run `python -m whisperlivekit.basic_server` instead
#   STT_BACKEND=mlx-whisper            STT_BACKEND_POLICY=simulstreaming
#
# The STTLIVE_STT_* names are the documented public knobs; the older STT_* names
# still work as fallbacks so nothing that already set them breaks. Defaults
# preserve the exact working macOS Apple Silicon command.
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
  echo "  Set up the STT venv (see README 'STT server'):" >&2
  echo "    uv venv --python 3.12 .venv" >&2
  echo "    uv pip install --python .venv -e ./WhisperLiveKit" >&2
  echo "    uv pip install --python .venv mlx-whisper" >&2
  echo "  ...or point STT_PYTHON at an interpreter that has whisperlivekit." >&2
  exit 1
fi

# STTLIVE_STT_* is the documented name; STT_* is the legacy fallback; then default.
MODEL="${STTLIVE_STT_MODEL:-${STT_MODEL:-large-v3-turbo}}"
BACKEND="${STT_BACKEND:-mlx-whisper}"
POLICY="${STT_BACKEND_POLICY:-simulstreaming}"
LANG="${STTLIVE_STT_LANGUAGE:-${STT_LANGUAGE:-auto}}"
HOST="${STTLIVE_STT_HOST:-${STT_HOST:-localhost}}"
PORT="${STTLIVE_STT_PORT:-${STT_PORT:-8000}}"

echo "Starting WhisperLiveKit STT"
echo "  Web UI:    http://${HOST}:${PORT}"
echo "  WebSocket: ws://${HOST}:${PORT}/asr"
echo "  Health:    http://${HOST}:${PORT}/health"
echo "  Command:   ${SERVER[*]} --model ${MODEL} --backend ${BACKEND} --backend-policy ${POLICY} --language ${LANG} --host ${HOST} --port ${PORT}"
exec "${SERVER[@]}" \
  --model "$MODEL" \
  --backend "$BACKEND" \
  --backend-policy "$POLICY" \
  --language "$LANG" \
  --host "$HOST" --port "$PORT"
