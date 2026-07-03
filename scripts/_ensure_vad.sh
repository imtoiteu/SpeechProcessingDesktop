#!/usr/bin/env bash
# Shared helper: guarantee the Silero VAD ONNX asset exists before STT starts.
#
# This file is meant to be SOURCED (not executed):  source scripts/_ensure_vad.sh
# It defines two functions:
#   vad_onnx_path      -> echoes the absolute path to silero_vad.onnx
#   ensure_vad_onnx    -> returns 0 if the asset is present (restores it if missing)
#
# The asset is committed to the repo, so a clean clone already has it. These helpers
# are a safety net: if the file is ever missing (e.g. an older *.onnx-ignoring clone,
# or an accidental delete) we restore it from the pinned upstream WhisperLiveKit tag
# so STT never fails with a cryptic "Model file not found: silero_vad.onnx".

# Pinned to the vendored WhisperLiveKit version (see WhisperLiveKit/pyproject.toml).
_VAD_UPSTREAM_URL="https://raw.githubusercontent.com/QuentinFuxa/WhisperLiveKit/v0.2.22/whisperlivekit/silero_vad_models/silero_vad.onnx"
_VAD_MIN_BYTES=1000000   # a real model is ~2.3 MB; anything tiny is an error page

vad_onnx_path() {
  local root="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
  echo "$root/WhisperLiveKit/whisperlivekit/silero_vad_models/silero_vad.onnx"
}

_vad_file_ok() {
  local f="$1"
  [[ -f "$f" ]] || return 1
  # portable byte size (macOS stat -f%z, GNU stat -c%s)
  local sz
  sz="$(stat -f%z "$f" 2>/dev/null || stat -c%s "$f" 2>/dev/null || echo 0)"
  [[ "$sz" -ge "$_VAD_MIN_BYTES" ]]
}

ensure_vad_onnx() {
  local f; f="$(vad_onnx_path)"
  if _vad_file_ok "$f"; then
    return 0
  fi
  echo "Silero VAD ONNX missing at: $f" >&2
  echo "Attempting to restore it from the pinned upstream tag..." >&2
  command -v curl >/dev/null 2>&1 || { echo "curl not found — cannot auto-restore the VAD asset." >&2; return 1; }
  mkdir -p "$(dirname "$f")"
  local tmp="${f}.download"
  if curl -sfL --max-time 60 "$_VAD_UPSTREAM_URL" -o "$tmp" && _vad_file_ok "$tmp"; then
    mv -f "$tmp" "$f"
    echo "Restored Silero VAD ONNX -> $f" >&2
    return 0
  fi
  rm -f "$tmp" 2>/dev/null || true
  echo "Failed to download the Silero VAD ONNX from:" >&2
  echo "  $_VAD_UPSTREAM_URL" >&2
  echo "Copy it manually into WhisperLiveKit/whisperlivekit/silero_vad_models/." >&2
  return 1
}
