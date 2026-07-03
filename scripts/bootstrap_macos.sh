#!/usr/bin/env bash
# One-shot, idempotent setup for a clean clone on macOS (Apple Silicon).
#
# Standardizes the project around TWO primary environments:
#   - root  .venv            -> STT  (WhisperLiveKit + mlx-whisper)   -> .venv/bin/whisperlivekit-server
#   - VieNeu-TTS/.venv       -> TTS  (vieneu + llama-cpp-python[metal] + trafilatura) -> .../bin/vieneu-stream
# ...and installs the desktop (Tauri) toolchain deps.
#
# It does NOT download heavy model weights (they lazy-download on first use).
# Pass --warm-tts to prefetch the TTS model into the HF cache.
#
# Usage:
#   ./scripts/bootstrap_macos.sh              # STT + TTS venvs + desktop deps
#   ./scripts/bootstrap_macos.sh --warm-tts   # ...and prefetch the TTS model
#
# Safe to re-run: existing venvs are reused; the Metal llama-cpp-python wheel is
# reinstalled every run because a bare `uv sync` inside VieNeu-TTS can prune it.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

WARM_TTS=0
for arg in "$@"; do
  case "$arg" in
    --warm-tts) WARM_TTS=1 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "Unknown flag: $arg" >&2; exit 2 ;;
  esac
done

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33mWARNING: %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# --- 0. OS + prerequisite checks ------------------------------------------
say "Checking prerequisites"
[[ "$(uname -s)" == "Darwin" ]] || die "This script is for macOS. On Linux use scripts/bootstrap_linux.sh."
[[ "$(uname -m)" == "arm64" ]] || warn "Not Apple Silicon (arm64). MLX/Metal acceleration requires Apple Silicon; STT/TTS will be slow or unavailable."

command -v uv >/dev/null 2>&1 || die "uv not found. Install it:  curl -LsSf https://astral.sh/uv/install.sh | sh   (or: brew install uv)"
command -v ffmpeg >/dev/null 2>&1 || warn "ffmpeg not found (needed for file/video decode). Install:  brew install ffmpeg"
command -v node >/dev/null 2>&1 || warn "node not found (needed to build the desktop app). Install:  brew install node"
command -v npm  >/dev/null 2>&1 || warn "npm not found (needed to build the desktop app). Install:  brew install node"
command -v cargo >/dev/null 2>&1 || warn "cargo/Rust not found (needed to build the desktop app). Install:  https://rustup.rs"
echo "uv: $(uv --version 2>/dev/null || echo '?')"

# --- 1. Root STT venv ------------------------------------------------------
say "Setting up root STT venv (.venv)"
uv venv --python 3.12 .venv
uv pip install --python .venv -e ./WhisperLiveKit
uv pip install --python .venv mlx-whisper
[[ -x ".venv/bin/whisperlivekit-server" ]] \
  || die "Expected .venv/bin/whisperlivekit-server after install — STT setup failed."
echo "OK: .venv/bin/whisperlivekit-server"

# --- 2. VieNeu-TTS venv ----------------------------------------------------
say "Setting up VieNeu-TTS venv (VieNeu-TTS/.venv)"
(
  cd VieNeu-TTS
  uv sync
  # A bare `uv sync` installs the torch-free core but NOT llama-cpp-python or
  # trafilatura (they live in the heavy optional group) — and a later re-sync can
  # prune them. Reinstall the Metal wheel every bootstrap so it stays present.
  uv pip install --python .venv "llama-cpp-python==0.3.16" \
      --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/metal/ \
      --index-strategy unsafe-best-match
  uv pip install --python .venv "trafilatura>=2.0.0"
)
# Verify the actual TTS runtime the server needs. vieneu-stream is the packaged
# CLI; the server (scripts/run_tts_server.sh) runs `python -m tts.server` and
# imports vieneu + llama_cpp, so verify those imports too.
TTS_PY="VieNeu-TTS/.venv/bin/python"
[[ -x "$TTS_PY" ]] || die "VieNeu-TTS/.venv/bin/python missing — TTS setup failed."
[[ -x "VieNeu-TTS/.venv/bin/vieneu-stream" ]] \
  && echo "OK: VieNeu-TTS/.venv/bin/vieneu-stream" \
  || warn "VieNeu-TTS/.venv/bin/vieneu-stream not found (server uses 'python -m tts.server', so this may be fine)."
"$TTS_PY" -c "import vieneu"     >/dev/null 2>&1 && echo "OK: import vieneu"     || die "'vieneu' not importable in VieNeu-TTS/.venv."
"$TTS_PY" -c "import llama_cpp"  >/dev/null 2>&1 && echo "OK: import llama_cpp"  || die "'llama_cpp' not importable — Metal wheel install failed."
"$TTS_PY" -c "import trafilatura">/dev/null 2>&1 && echo "OK: import trafilatura" || warn "'trafilatura' missing — URL-to-speech extraction will be disabled."

# --- 3. Desktop (Tauri) deps ----------------------------------------------
if command -v npm >/dev/null 2>&1; then
  say "Installing desktop app deps (npm) + generating icons"
  ( cd desktop && npm install && npm run icon )
  echo "OK: desktop npm deps + icons"
else
  warn "Skipping desktop deps (npm missing)."
fi

# --- 4. Optional: warm the TTS model cache --------------------------------
if [[ "$WARM_TTS" == "1" ]]; then
  say "Prefetching the TTS model into the HF cache (--warm-tts)"
  ./scripts/download_tts_model.sh
fi

# --- Done ------------------------------------------------------------------
cat <<'EOF'

==> Bootstrap complete.

Next:
  ./scripts/build_desktop_macos.sh      # build STTLive.app
  ./scripts/open_desktop_macos.sh       # launch it

Manual / debug (run servers directly, no desktop app):
  ./scripts/run_stt_server.sh           # STT  on http://localhost:8000
  ./scripts/run_tts_server.sh           # TTS  on http://localhost:8011
  ./scripts/run_web_macos.sh            # STT web UI (same as run_stt_server.sh)

Optional:
  ./scripts/bootstrap_macos.sh --warm-tts   # prefetch TTS model
  ./scripts/setup_chunkformer.sh            # enable Batch + ChunkFormer (Vietnamese)
  ./scripts/diagnose_env.sh                 # print an environment report
EOF
