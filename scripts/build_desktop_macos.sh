#!/usr/bin/env bash
# Build the STTLive desktop app (Tauri) on macOS.
#
#   ./scripts/build_desktop_macos.sh
#
# Produces a signed-by-default-adhoc .app bundle. Requires Node/npm and Rust
# (run ./scripts/bootstrap_macos.sh first).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

command -v npm  >/dev/null 2>&1 || { echo "ERROR: npm not found. brew install node" >&2; exit 1; }
command -v cargo >/dev/null 2>&1 || { echo "ERROR: cargo/Rust not found. See https://rustup.rs" >&2; exit 1; }

cd desktop
npm install
npm run icon
npm run build

APP="$REPO_ROOT/desktop/src-tauri/target/release/bundle/macos/STTLive.app"
echo
if [[ -d "$APP" ]]; then
  echo "Built: $APP"
  echo "Launch with: ./scripts/open_desktop_macos.sh"
else
  echo "Build finished but STTLive.app was not found at:" >&2
  echo "  $APP" >&2
  echo "Check the tauri build output above for errors." >&2
  exit 1
fi
