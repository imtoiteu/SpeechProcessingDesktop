#!/usr/bin/env bash
# Prefetch the VieNeu-TTS model + codec into the Hugging Face cache.
#
# This is optional: the sidecar downloads on first request. Run it to warm the
# cache ahead of time (e.g. before going offline). It is idempotent — already
# cached files are skipped.
#
#   ./scripts/download_tts_model.sh                       # q8 backbone (default)
#   TTS_BACKBONE=pnnbao-ump/VieNeu-TTS-0.3B-q4-gguf ./scripts/download_tts_model.sh
#
# The VieNeu repos are PUBLIC (no gating). A HF token only raises rate limits:
#   HF_TOKEN=hf_xxx ./scripts/download_tts_model.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BACKBONE="${TTS_BACKBONE:-pnnbao-ump/VieNeu-TTS-0.3B-q8-gguf}"
CODEC="${TTS_CODEC:-neuphonic/neucodec-onnx-decoder-int8}"

# Prefer the VieNeu venv; fall back to the STT venv or system python.
PY=""
for cand in "${TTS_PYTHON:-${TTS_VENV:-VieNeu-TTS/.venv}/bin/python}" ".venv/bin/python" "python3"; do
  if [[ -x "$cand" ]] || command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done
if [[ -z "$PY" ]]; then
  echo "No python interpreter found (set up VieNeu-TTS/.venv first)." >&2
  exit 1
fi

echo "Prefetching VieNeu-TTS into the HF cache (using $PY)"
echo "  backbone: $BACKBONE"
echo "  codec:    $CODEC"
"$PY" - "$BACKBONE" "$CODEC" <<'PYEOF'
import os, sys
from huggingface_hub import snapshot_download
from huggingface_hub.errors import RepositoryNotFoundError

token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
for repo_id in sys.argv[1:]:
    try:
        path = snapshot_download(repo_id, token=token)  # into the shared HF cache
        print("Cached:", repo_id, "->", path)
    except RepositoryNotFoundError:
        print("ERROR: repo '%s' not found." % repo_id, file=sys.stderr)
        sys.exit(3)
PYEOF

echo "Done. Launch with: ./scripts/run_tts_server.sh"
