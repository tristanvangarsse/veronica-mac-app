#!/bin/bash
set -euo pipefail
umask 077
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/.build/engine"
OUT="$ROOT/macos/Veronica/Resources/VeronicaEngine"
PYTHON_BIN="${PYTHON_BIN:-$ROOT/.venv/bin/python}"
[[ "$(uname -s)" == Darwin ]] || { echo "macOS required" >&2; exit 2; }
"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11 or newer is required"'
mkdir -p "$BUILD" "$OUT"
"$PYTHON_BIN" -m venv --clear "$BUILD/venv"
"$BUILD/venv/bin/python" -m pip install --require-hashes -r "$ROOT/requirements/development.txt"
rm -rf "$BUILD/MediaTools"
"$BUILD/venv/bin/python" "$ROOT/scripts/bundle_media_tools.py" --output "$BUILD/MediaTools"
"$BUILD/venv/bin/python" "$ROOT/scripts/release_manifest.py" --generate "$BUILD/security-manifest.json"
"$BUILD/venv/bin/python" "$ROOT/scripts/collect_runtime_notices.py" "$BUILD/notices"
cd "$ROOT"
"$BUILD/venv/bin/python" -m PyInstaller --clean --noconfirm --onedir \
  --name veronica-engine --paths "$ROOT" --hidden-import PIL --hidden-import media_worker --hidden-import media_dates --hidden-import media_change_log \
  --add-data "$BUILD/security-manifest.json:." --add-data "$ROOT/preset-720P.json:." \
  --add-data "$BUILD/ExifTool:ExifTool" --add-data "$BUILD/notices:licenses" veronica.py
# PyInstaller rewrites discovered Mach-O load commands. These tools are already
# relocated, signed and hashed together; preserve that exact attested payload.
cp -R "$BUILD/MediaTools" "$ROOT/dist/veronica-engine/_internal/MediaTools"
"$BUILD/venv/bin/python" scripts/release_manifest.py --check "$ROOT/dist/veronica-engine/veronica-engine"
# Replace only the known generated engine destination, after validation succeeds.
find "$OUT" -mindepth 1 ! -name README.txt -exec rm -rf {} +
cp -R "$ROOT/dist/veronica-engine/." "$OUT/"
cp "$ROOT/preset-720P.json" "$OUT/preset-720P.json"
"$BUILD/venv/bin/python" scripts/release_manifest.py --check "$OUT/veronica-engine"
printf 'Verified standalone engine: %s\n' "$OUT/veronica-engine"
