#!/usr/bin/env bash
# Run the STTLive desktop app in Tauri dev mode (hot-reload wrapper) on macOS.
#
#   ./scripts/dev_desktop_macos.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT/desktop"

command -v npm >/dev/null 2>&1 || { echo "ERROR: npm not found. brew install node" >&2; exit 1; }

npm install
exec npm run dev
