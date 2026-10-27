#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/.build"
BUILD_ROOT="$(mktemp -d "$ROOT/.build/local-release.XXXXXXXX")"
DERIVED="$BUILD_ROOT/DerivedData"
EXPORT="$BUILD_ROOT/release"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script must be run on macOS." >&2
  exit 2
fi
command -v xcodegen >/dev/null || { echo "xcodegen is required" >&2; exit 2; }

/usr/bin/swift "$ROOT/scripts/build_app_icon_macos.swift"
bash "$ROOT/scripts/sync_engine_bundle.sh"
bash "$ROOT/scripts/build_standalone_engine_macos.sh"
MIN_MACOS="$("$ROOT/.venv/bin/python" "$ROOT/scripts/release_manifest.py" --minimum-os "$ROOT/macos/Veronica/Resources/VeronicaEngine/veronica-engine")"
cd "$ROOT/macos"
xcodegen generate
mkdir -p "$EXPORT"
xcodebuild \
  -project Veronica.xcodeproj \
  -scheme Veronica \
  -configuration Release \
  -derivedDataPath "$DERIVED" \
  CODE_SIGNING_ALLOWED=NO \
  MACOSX_DEPLOYMENT_TARGET="$MIN_MACOS" \
  build
cp -R "$DERIVED/Build/Products/Release/Veronica.app" "$EXPORT/Veronica.app"

"$ROOT/.venv/bin/python" "$ROOT/scripts/sign_app_macos.py" "$EXPORT/Veronica.app"
bash "$ROOT/scripts/check_release_readiness_macos.sh" "$EXPORT/Veronica.app"
echo "Local ad-hoc signed app: $EXPORT/Veronica.app"

if command -v hdiutil >/dev/null; then
  rm -f "$EXPORT/Veronica-local.dmg"
  hdiutil create -volname Veronica -srcfolder "$EXPORT/Veronica.app" -ov -format UDZO "$EXPORT/Veronica-local.dmg" >/dev/null
  echo "Local development DMG: $EXPORT/Veronica-local.dmg"
fi

# Leave both the running app and the previous verified release intact.
# Every build has its own output directory, including while signing/verifying.
echo "Verified build retained at: $EXPORT"
