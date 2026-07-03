#!/usr/bin/env bash
# Run the STT web server (WhisperLiveKit) for manual/browser use on macOS.
#
# This is a thin alias for scripts/run_stt_server.sh: the same server serves the
# streaming WebSocket (/asr), the batch REST API (/v1/audio/transcriptions) AND
# the web UI at http://localhost:8000. Open that URL in a browser to use STT
# without the desktop app.
#
#   ./scripts/run_web_macos.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Web UI: http://localhost:${STTLIVE_STT_PORT:-${STT_PORT:-8000}}"
exec "$REPO_ROOT/scripts/run_stt_server.sh"
