#!/usr/bin/env bash
# OPTIONAL: enable the "Batch + ChunkFormer (Vietnamese)" model in the UI.
#
# ChunkFormer (khanhld/chunkformer-large-vie) is a Vietnamese CTC ASR model that
# the batch endpoint runs OUT OF PROCESS via a dedicated .venv-chunkformer. It is
# kept isolated on purpose: `chunkformer` pulls its own torch/torchaudio/
# transformers that would conflict with the STT and TTS venvs. The server code
# (WhisperLiveKit/whisperlivekit/batch_backends.py) hard-expects the interpreter at
# .venv-chunkformer/bin/python, so this venv IS required for that one UI feature —
# but only for it. Streaming, batch Whisper sizes and TTS work without it.
#
#   ./scripts/setup_chunkformer.sh
#
# After this, restart the STT server; the UI's Batch model list will show
# "ChunkFormer (Vietnamese)" as available. Model weights lazy-download on first use.
#
# NOTE: This has been validated on macOS Apple Silicon (MPS, with CPU fallback).
# On Linux/Windows it can run on CPU/CUDA but that path is not validated here.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

command -v uv >/dev/null 2>&1 || { echo "ERROR: uv not found. See https://astral.sh/uv" >&2; exit 1; }

echo "==> Creating .venv-chunkformer (isolated; separate from .venv and VieNeu-TTS/.venv)"
uv venv --python 3.12 .venv-chunkformer
uv pip install --python .venv-chunkformer -r requirements-chunkformer.txt

if [[ -x ".venv-chunkformer/bin/python" ]]; then
  echo "OK: .venv-chunkformer ready."
  echo "Restart STT (./scripts/run_stt_server.sh) — Batch + ChunkFormer (Vietnamese) is now selectable."
else
  echo "ERROR: .venv-chunkformer/bin/python missing after install." >&2
  exit 1
fi
