#!/usr/bin/env bash
# Build the STTLive desktop client (Tauri) on Linux.
#
#   ./scripts/build_desktop_linux.sh
#
# Requires Node/npm, Rust, and Tauri's Linux system deps (webkit2gtk, libsoup,
# etc.) — see docs/DESKTOP_APP.md. Tauri emits .deb / .AppImage / .rpm bundles
# under desktop/src-tauri/target/release/bundle/ depending on your distro.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

command -v npm   >/dev/null 2>&1 || { echo "ERROR: npm not found. Install Node.js." >&2; exit 1; }
command -v cargo >/dev/null 2>&1 || { echo "ERROR: cargo/Rust not found. See https://rustup.rs" >&2; exit 1; }

cd desktop
npm install
npm run icon
npm run build

BUNDLE_DIR="$REPO_ROOT/desktop/src-tauri/target/release/bundle"
echo
echo "Build finished. Bundles (if produced) are under:"
echo "  $BUNDLE_DIR"
echo "Look for deb/, appimage/ or rpm/ subfolders depending on your distro."
