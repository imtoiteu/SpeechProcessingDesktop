#!/usr/bin/env bash
# Setup for Linux. IMPORTANT — read this before assuming parity with macOS:
#
#   * The DESKTOP CLIENT (Tauri app) builds and runs on Linux.
#   * The LOCAL STT BACKEND on Linux uses `faster-whisper` (CPU, or CUDA if you
#     install a GPU ctranslate2 build). This is the upstream-supported path but it
#     has NOT been validated by this project — verify accuracy/speed yourself.
#   * There is NO MLX/Metal on Linux. Do not expect Apple-Silicon performance.
#   * The LOCAL TTS BACKEND needs a CPU or CUDA build of llama-cpp-python (NOT the
#     macOS Metal wheel). That path is likewise unvalidated here.
#   * RECOMMENDED on Linux: run the desktop app in **Remote Server Mode** pointing
#     at a macOS (or otherwise validated) STT/TTS host on your LAN.
#
# This script sets up the DESKTOP CLIENT deps and OPTIONALLY the local STT venv.
# It will not pretend the local backends are validated.
#
#   ./scripts/bootstrap_linux.sh              # desktop client deps only (recommended)
#   ./scripts/bootstrap_linux.sh --with-stt   # ...also create a local faster-whisper STT venv
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

WITH_STT=0
for arg in "$@"; do
  case "$arg" in
    --with-stt) WITH_STT=1 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "Unknown flag: $arg" >&2; exit 2 ;;
  esac
done

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33mWARNING: %s\033[0m\n' "$*" >&2; }

[[ "$(uname -s)" == "Linux" ]] || warn "This script targets Linux (uname=$(uname -s))."

say "Checking prerequisites"
command -v node >/dev/null 2>&1 || warn "node missing (needed for the desktop app). See https://nodejs.org"
command -v npm  >/dev/null 2>&1 || warn "npm missing (needed for the desktop app)."
command -v cargo >/dev/null 2>&1 || warn "cargo/Rust missing (needed for the desktop app). See https://rustup.rs"
command -v ffmpeg >/dev/null 2>&1 || warn "ffmpeg missing (needed for file/video decode). e.g. apt install ffmpeg"
# Tauri on Linux also needs system webkit2gtk / libsoup dev packages — see docs.
warn "Tauri on Linux requires system libs (webkit2gtk, libsoup, etc). See docs/DESKTOP_APP.md → Linux."

say "Installing desktop app deps (npm) + generating icons"
if command -v npm >/dev/null 2>&1; then
  ( cd desktop && npm install && npm run icon )
  echo "OK: desktop npm deps + icons"
else
  warn "Skipping desktop deps (npm missing)."
fi

if [[ "$WITH_STT" == "1" ]]; then
  say "Creating a LOCAL faster-whisper STT venv (UNVALIDATED on Linux)"
  command -v uv >/dev/null 2>&1 || { echo "uv required for --with-stt. See https://astral.sh/uv" >&2; exit 1; }
  uv venv --python 3.12 .venv
  uv pip install --python .venv -e ./WhisperLiveKit
  # faster-whisper is the cross-platform CPU backend. For CUDA, install a GPU
  # ctranslate2 build yourself (see faster-whisper docs) — not done automatically.
  uv pip install --python .venv faster-whisper
  echo "OK: .venv (faster-whisper). Start it with: scripts/run_stt_linux.sh"
  warn "Local STT on Linux is unvalidated by this project — verify before relying on it."
  echo
  echo "Local TTS on Linux: install a CPU/CUDA llama-cpp-python wheel into VieNeu-TTS/.venv"
  echo "  (NOT the macOS Metal wheel). See docs/DESKTOP_APP.md → Linux. Unvalidated here."
fi

cat <<'EOF'

==> Linux bootstrap complete.

Build the desktop client:
  ./scripts/build_desktop_linux.sh
  ./scripts/open_desktop_linux.sh

Recommended runtime: launch the app and choose **Remote Server Mode**, pointing
STT/TTS at a validated host (e.g. a Mac on your LAN).
EOF
