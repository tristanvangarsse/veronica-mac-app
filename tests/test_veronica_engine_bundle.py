#!/usr/bin/env python3
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    bundle = root / "macos" / "Veronica" / "Resources" / "Engine"
    for name in ("veronica.py", "media_maintenance.py", "media_audit.py", "media_security.py", "media_worker.py", "preset-720P.json"):
        assert (root / name).read_bytes() == (bundle / name).read_bytes(), f"stale bundled engine file: {name}"
    print("Veronica bundled engine sync: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
