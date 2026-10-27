#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="${1:-}"
ENGINE="$ROOT/macos/Veronica/Resources/VeronicaEngine/veronica-engine"
if [[ -n "$APP" ]]; then ENGINE="$APP/Contents/Resources/VeronicaEngine/veronica-engine"; fi
"$ROOT/.venv/bin/python" "$ROOT/scripts/release_manifest.py" --check "$ENGINE"
if [[ -n "$APP" ]]; then
  /usr/bin/codesign --verify --deep --strict --verbose=2 "$APP"
  "$ROOT/.venv/bin/python" - "$ROOT" "$ENGINE" "$APP" <<'PYCODE'
import importlib.util,plistlib,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('release_manifest',Path(sys.argv[1])/'scripts/release_manifest.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
required=tuple(map(int,module.minimum_os(sys.argv[2]).split('.')))
with (Path(sys.argv[3])/'Contents/Info.plist').open('rb') as f:info=plistlib.load(f)
declared=tuple(map(int,info['LSMinimumSystemVersion'].split('.')))
if declared<required:raise SystemExit('The app declares an older macOS than its runtime/tools support')
print('Declared macOS support matches the bundled runtime and approved tools')
PYCODE
fi
if [[ "${VERONICA_PUBLIC_RELEASE:-0}" == 1 ]]; then
  [[ -n "$APP" ]] || { echo "Public verification requires the final app" >&2; exit 2; }
  /usr/bin/codesign -dv --verbose=4 "$APP" 2>&1 | /usr/bin/grep -q 'Authority=Developer ID Application:' || { echo "Public release requires Developer ID signing" >&2; exit 2; }
  xcrun stapler validate "$APP"
  /usr/sbin/spctl --assess --type execute --verbose=2 "$APP"
  echo "Public signing and notarization verification passed."
else
  echo "Local integrity checks passed. Public distribution still requires Developer ID signing, notarization and clean-Mac acceptance."
fi
