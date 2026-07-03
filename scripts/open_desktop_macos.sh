#!/usr/bin/env bash
# Launch the already-built STTLive desktop app on macOS.
#
#   ./scripts/open_desktop_macos.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$REPO_ROOT/desktop/src-tauri/target/release/bundle/macos/STTLive.app"

if [[ ! -d "$APP" ]]; then
  echo "STTLive.app not found." >&2
  echo "Please run ./scripts/build_desktop_macos.sh first." >&2
  exit 1
fi

echo "Opening $APP"
open "$APP"
