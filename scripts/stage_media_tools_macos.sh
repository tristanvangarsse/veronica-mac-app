#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[[ "$(uname -s)" == Darwin ]] || { echo "macOS required" >&2; exit 2; }
mkdir -p "$ROOT/.build"
STAGING="$(mktemp -d "$ROOT/.build/portable-tools.XXXXXXXX")"
"$ROOT/.venv/bin/python" "$ROOT/scripts/bundle_media_tools.py" --output "$STAGING/MediaTools"
echo "Verified portable tools, libraries and supplied notices: $STAGING/MediaTools"
echo "Normal app builds include this preparation automatically."
