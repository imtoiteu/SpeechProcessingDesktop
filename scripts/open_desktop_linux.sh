#!/usr/bin/env bash
# Launch the STTLive desktop client on Linux.
#
#   ./scripts/open_desktop_linux.sh
#
# Tauri's Linux binary name is the productName lowercased ("sttlive"). We try the
# raw release binary first (works without installing a bundle), then fall back to
# a PATH-installed command if you installed the .deb/.rpm/.AppImage.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="$REPO_ROOT/desktop/src-tauri/target/release/sttlive"

if [[ -x "$BIN" ]]; then
  echo "Launching $BIN"
  exec "$BIN"
elif command -v sttlive >/dev/null 2>&1; then
  echo "Launching installed 'sttlive'"
  exec sttlive
else
  echo "STTLive binary not found at:" >&2
  echo "  $BIN" >&2
  echo "Please run ./scripts/build_desktop_linux.sh first (or install the produced bundle)." >&2
  exit 1
fi
