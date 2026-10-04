#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENGINE="$ROOT/macos/Veronica/Resources/VeronicaEngine/veronica-engine"
TOOLS_DIR="$ROOT/macos/Veronica/Resources/Tools/bin"

fail=0
external=0

echo "=== Veronica standalone engine ==="
if [[ -x "$ENGINE" ]]; then
  echo "OK bundled: $ENGINE"

  echo "Smoke-testing bundled engine..."
  if "$ENGINE" ui-snapshot >/dev/null; then
    echo "OK engine smoke test: ui-snapshot"
  else
    echo "BROKEN bundled engine: ui-snapshot failed" >&2
    fail=1
  fi
else
  echo "MISSING bundled engine: $ENGINE" >&2
  fail=1
fi

echo
echo "=== Media tools ==="

for tool in ffmpeg ffprobe HandBrakeCLI; do
  bundled="$TOOLS_DIR/$tool"

  if [[ -x "$bundled" ]]; then
    echo "OK bundled: $tool -> $bundled"
    continue
  fi

  external_path="$(command -v "$tool" || true)"
  if [[ -n "$external_path" ]]; then
    echo "OK external dependency: $tool -> $external_path"
    external=1
  else
    echo "MISSING: $tool (not bundled and not available on PATH)" >&2
    fail=1
  fi
done

if [[ $fail -ne 0 ]]; then
  echo >&2
  echo "Release readiness FAILED." >&2
  echo "Veronica requires its bundled standalone engine plus ffmpeg, ffprobe, and HandBrakeCLI." >&2
  echo "Media tools may be bundled as portable redistributable binaries or installed externally." >&2
  exit 2
fi

echo
if [[ $external -ne 0 ]]; then
  echo "Release dependency model: external media tools."
  echo "The Veronica engine is bundled, but the app is not fully self-contained."
  echo "A clean Mac must install ffmpeg/ffprobe and HandBrakeCLI (for example via Homebrew)."
else
  echo "Release dependency model: bundled media tools."
  echo "Standalone engine and required media executables are present in the resource tree."
fi

echo
echo "Resource/dependency readiness passed."
echo "Signing, notarization, licensing, and final app-bundle verification are still required for public release."
