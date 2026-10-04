#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/.build/engine"
OUT="$ROOT/macos/Veronica/Resources/VeronicaEngine"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script must be run on macOS." >&2
  exit 2
fi

rm -rf "$BUILD"
mkdir -p "$BUILD" "$OUT"
"$PYTHON_BIN" -m venv "$BUILD/venv"
"$BUILD/venv/bin/python" -m pip install --upgrade pip
"$BUILD/venv/bin/python" -m pip install "pyinstaller>=6,<7" "Pillow==11.3.0"

cd "$ROOT"
"$BUILD/venv/bin/pyinstaller" \
  --clean \
  --noconfirm \
  --onedir \
  --name veronica-engine \
  --paths "$ROOT" \
  --hidden-import PIL \
  veronica.py

# Keep the tracked README, but replace all generated release-engine contents.
find "$OUT" -mindepth 1 ! -name "README.txt" -exec rm -rf {} +

cp -R "$ROOT/dist/veronica-engine/." "$OUT/"
chmod 755 "$OUT/veronica-engine"

cp "$ROOT/preset-720P.json" "$OUT/preset-720P.json"

echo "Standalone Veronica engine staged at $OUT/veronica-engine"
echo "Engine bundle size:"
du -sh "$OUT"
