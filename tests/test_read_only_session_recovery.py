#!/usr/bin/env python3
"""A refused write must preserve the source and release verified recovery copies."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

from PIL import Image
from fixture_dates import exif_date

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix="veronica-read-only-recovery-") as td:
        base = Path(td).resolve()
        media = base / "Photos"
        media.mkdir()
        source = media / "photo.png"
        Image.effect_noise((1600, 1200), 65).convert("RGB").save(source, exif=exif_date())
        original = source.read_bytes()
        expected = hashlib.sha256(original).hexdigest()
        state = base / "Preferences"
        session = state / "Sessions.noindex" / str(uuid.uuid4())

        def run(command, *args, ok=True):
            command_args = [sys.executable, str(ROOT / "veronica.py"), command, "--state-dir", str(state)]
            if command in {"analyze-all", "annual-all", "desktop-session"}:
                command_args += ["--session-dir", str(session)]
            result = subprocess.run([*command_args, *map(str, args)], capture_output=True, text=True, timeout=120)
            assert (result.returncode == 0) == ok, result.stdout + result.stderr
            return json.loads(result.stdout) if result.stdout.startswith("{") else result.stdout + result.stderr

        run("configure-folders", "--add", media)
        recipe = run("folder-settings", "--folder", media)["recipe"]
        recipe["filename_policy"]["enabled"] = False
        run("configure-folder", "--folder", media, "--recipe-json", json.dumps(recipe))
        run("analyze-all")
        offline = base / "Disconnected"
        media.rename(offline)
        try:
            assert "unavailable" in run("annual-all", "--yes", ok=False).lower()
            assert (offline / source.name).read_bytes() == original
        finally:
            offline.rename(media)
        media.chmod(0o555)
        try:
            run("annual-all", "--yes", ok=False)
            assert source.read_bytes() == original
        finally:
            media.chmod(0o755)

        recovery = run("desktop-session")
        retained = [Path(path) for path in recovery["original_folders"]]
        assert retained, "The verified recovery original must remain recoverable"
        copies = [p for folder in retained for p in folder.rglob("*") if p.is_file()]
        assert copies and all(hashlib.sha256(p.read_bytes()).hexdigest() == expected for p in copies)
        assert "before discarding" in run("desktop-session", "--discard", ok=False)

        # A known path with changed bytes must still block cleanup.
        copies[0].write_bytes(b"Changed recovery original")
        assert "original changed" in run("desktop-session", ok=False).lower()
        copies[0].write_bytes(original)
        unknown = retained[0] / "unrecognized-file.txt"
        unknown.write_text("This must not be silently discarded")
        assert "Unrecognized recovery files" in run("desktop-session", ok=False)
        unknown.unlink()
        assert run("desktop-session")["original_folders"]

        # Preserve only these generated test copies outside the session, then
        # verify that the normal close/reopen path can release scratch records.
        for index, folder in enumerate(retained):
            folder.rename(base / f"Recovered original {index}")
        run("desktop-session", "--discard")
        assert not session.exists() and source.read_bytes() == original
        session = state / "Sessions.noindex" / str(uuid.uuid4())
        run("analyze-all")
        result = run("annual-all", "--yes")
        assert (media / "photo.jpg").is_file(), (list(media.iterdir()), result)
        assert run("desktop-session")["original_folders"]
    print("Unavailable/read-only library, exact recovery copies, tamper refusal and successful retry: PASS")


if __name__ == "__main__":
    main()
