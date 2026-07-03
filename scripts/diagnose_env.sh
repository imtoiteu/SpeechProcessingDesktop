#!/usr/bin/env bash
# Print an environment report so you can tell, at a glance, whether this clone is
# set up correctly — and which venvs are the CURRENT ones vs. old/experimental.
#
#   ./scripts/diagnose_env.sh
#
# Read-only: it never installs, downloads, or starts anything.
set -uo pipefail   # intentionally NOT -e: keep reporting even when a check fails

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

hdr()  { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
row()  { printf '  %-34s %s\n' "$1" "$2"; }
have() { command -v "$1" >/dev/null 2>&1 && echo "$($1 --version 2>&1 | head -n1)" || echo "MISSING"; }
yn()   { [[ -e "$1" ]] && echo "yes" || echo "NO"; }
xyn()  { [[ -x "$1" ]] && echo "yes" || echo "NO"; }

hdr "System"
row "OS"           "$(uname -s) $(uname -r)"
row "Arch"         "$(uname -m)"

hdr "Toolchain"
row "python3"      "$(have python3)"
row "uv"           "$(have uv)"
row "ffmpeg"       "$(command -v ffmpeg >/dev/null 2>&1 && ffmpeg -version 2>/dev/null | head -n1 || echo MISSING)"
row "node"         "$(have node)"
row "npm"          "$(have npm)"
row "cargo"        "$(have cargo)"

hdr "STT environment (root .venv)"
row ".venv exists"                    "$(yn .venv)"
row ".venv/bin/whisperlivekit-server" "$(xyn .venv/bin/whisperlivekit-server)"
if [[ -x .venv/bin/python ]]; then
  row "  import mlx_whisper" "$(.venv/bin/python -c 'import mlx_whisper' 2>/dev/null && echo ok || echo NO)"
fi
# Required Silero VAD ONNX asset (committed; STT fails to start without it).
VAD="WhisperLiveKit/whisperlivekit/silero_vad_models/silero_vad.onnx"
if [[ -f "$VAD" ]]; then
  VAD_SZ="$(stat -f%z "$VAD" 2>/dev/null || stat -c%s "$VAD" 2>/dev/null || echo 0)"
  if [[ "$VAD_SZ" -ge 1000000 ]]; then row "silero_vad.onnx (required)" "yes (${VAD_SZ} bytes)"; else row "silero_vad.onnx (required)" "PRESENT BUT TOO SMALL (${VAD_SZ} bytes) — corrupt?"; fi
else
  row "silero_vad.onnx (required)" "NO — STT will fail to start; run ./scripts/bootstrap_macos.sh"
fi

hdr "TTS environment (VieNeu-TTS/.venv)"
row "VieNeu-TTS/.venv exists"       "$(yn VieNeu-TTS/.venv)"
row "  bin/vieneu-stream"           "$(xyn VieNeu-TTS/.venv/bin/vieneu-stream)"
if [[ -x VieNeu-TTS/.venv/bin/python ]]; then
  PY=VieNeu-TTS/.venv/bin/python
  row "  import vieneu"      "$($PY -c 'import vieneu'      2>/dev/null && echo ok || echo NO)"
  row "  import llama_cpp"   "$($PY -c 'import llama_cpp'   2>/dev/null && echo ok || echo 'NO (Metal wheel missing)')"
  row "  import trafilatura" "$($PY -c 'import trafilatura' 2>/dev/null && echo ok || echo 'NO (URL extract off)')"
fi

hdr "Optional: ChunkFormer (Vietnamese batch)"
row ".venv-chunkformer exists"       "$(yn .venv-chunkformer)"
row "  bin/python"                   "$(xyn .venv-chunkformer/bin/python)"
row "  scripts/chunkformer_transcribe.py" "$(yn scripts/chunkformer_transcribe.py)"

hdr "Old / experimental (should NOT be depended on)"
row ".venv-stage0 present"           "$(yn .venv-stage0)"
row ".venv-tts present (legacy)"     "$(yn .venv-tts)"

hdr "Desktop app"
row "desktop/package.json"                   "$(yn desktop/package.json)"
row "desktop/src-tauri/tauri.conf.json"      "$(yn desktop/src-tauri/tauri.conf.json)"
row "desktop/node_modules"                   "$(yn desktop/node_modules)"
row "built STTLive.app"                      "$(yn desktop/src-tauri/target/release/bundle/macos/STTLive.app)"

hdr "Config (created at first launch, outside the repo)"
case "$(uname -s)" in
  Darwin) CFG="$HOME/Library/Application Support/STTLive/config.json" ;;
  *)      CFG="$HOME/.config/STTLive/config.json" ;;
esac
row "$CFG" "$(yn "$CFG")"

echo
echo "Tip: after a clean clone run ./scripts/bootstrap_macos.sh, then re-run this."
