#!/usr/bin/env python3
"""Exercise the desktop's fresh-launch, Trash, and interrupted-work lifecycle."""
import fcntl
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid

from PIL import Image
from fixture_dates import exif_date

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import media_security as security


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, default=ROOT / "veronica.py")
    engine = parser.parse_args().engine.resolve()
    command_prefix = [sys.executable, str(engine)] if engine.suffix == ".py" else [str(engine)]
    with tempfile.TemporaryDirectory(prefix="veronica-desktop-sessions-") as td:
        base = Path(td).resolve()
        preferences = base / "Preferences"
        photos = base / "Photos"
        photos.mkdir()
        source = photos / "photo.jpg"
        Image.frombytes("RGB", (1800, 1200), os.urandom(1800 * 1200 * 3)).save(source, quality=100, subsampling=0, exif=exif_date())
        original = source.read_bytes()

        def run(command, *arguments, session=None, success=True):
            args = [*command_prefix, command,
                    "--state-dir", str(preferences), *map(str, arguments)]
            if session is not None:
                args += ["--session-dir", str(session)]
            result = subprocess.run(args, text=True, capture_output=True, timeout=120)
            if not success:
                assert result.returncode != 0, result.stdout
                return result.stderr + result.stdout
            assert result.returncode == 0, result.stdout + result.stderr
            return json.loads(result.stdout) if result.stdout.startswith("{") else result.stdout

        def new_session():
            return preferences / "Sessions.noindex" / str(uuid.uuid4())

        run("configure-folders", "--add", photos)
        recipe = run("folder-settings", "--folder", photos)["recipe"]
        recipe["date_scope"] = {"mode": "all", "start": None, "end": None, "legacy": False}
        recipe["filename_policy"]["enabled"] = False
        run("configure-folder", "--folder", photos, "--recipe-json", json.dumps(recipe))
        other = base / "Other folder"
        other.mkdir()
        run("configure-folders", "--add", other)
        other_recipe = run("folder-settings", "--folder", other)["recipe"]
        other_recipe["optimization_settings"]["jpeg_quality"] = 91
        run("configure-folder", "--folder", other, "--recipe-json", json.dumps(other_recipe))
        run("analyze-all")  # Deliberately leave a legacy persistent catalogue.
        legacy = run("ui-snapshot")
        legacy_state = Path(legacy["folder_settings"][0]["state_dir"])
        legacy_original = legacy_state / "quarantine" / "old-original.jpg"
        legacy_original.parent.mkdir(parents=True)
        legacy_original.write_bytes(b"An older original must never be discarded.")
        legacy_db = legacy_state / "media-maintenance.sqlite"
        legacy_db_before = hashlib.sha256(legacy_db.read_bytes()).hexdigest()

        session = new_session()
        snapshot = run("ui-snapshot", session=session)
        assert snapshot["latest_plan"] is None and snapshot["active_assets"] == 0
        assert snapshot["recent_changes"] == [] and snapshot["committed_outputs"] == 0
        assert snapshot["folder_settings"][0]["recipe"] == recipe
        assert snapshot["folder_settings"][1]["recipe"] == other_recipe
        run("analyze-all", session=session)
        page = run("scan-results", session=session)
        assert page["total"] == 1 and page["counts"]["changes"] == 1, page
        assert source.read_bytes() == original, "Scanning must not modify originals"

        # A second app's lease prevents another launch from discarding it.
        with (session / ".lease").open("a+") as lease:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert run("desktop-session", "--discard", session=session)["busy"]
            assert session.is_dir()

        # Preference changes persist, and invalidate this session's frozen plan.
        recipe["optimization_settings"]["jpeg_quality"] = 74
        run("configure-folder", "--folder", photos, "--recipe-json", json.dumps(recipe))
        assert "Scan folders again" in run("scan-results", session=session, success=False)
        run("analyze-all", session=session)
        cleanup = run("annual-all", "--yes", session=session)
        assert source.is_file() and source.read_bytes() != original, cleanup
        release = run("desktop-session", session=session)
        originals = [Path(p) for p in release["original_folders"]]
        assert len(originals) == 1 and originals[0].name == "Veronica originals", release
        retained = list(originals[0].rglob("photo.jpg"))
        assert len(retained) == 1 and retained[0].read_bytes() == original
        assert "before discarding" in run("desktop-session", "--discard", session=session, success=False)
        assert session.exists() and retained[0].read_bytes() == original

        # Use the same native Trash API as the app, and only remove this test's
        # generated item after proving its bytes arrived intact in the Trash.
        swift = base / "trash.swift"
        swift.write_text('''import Foundation
var destination: NSURL?
try FileManager.default.trashItem(at: URL(fileURLWithPath: CommandLine.arguments[1]), resultingItemURL: &destination)
print(destination!.path!)
''')
        helper = base / "trash-helper"
        subprocess.run(["/usr/bin/swiftc", str(swift), "-o", str(helper)], check=True, timeout=90)

        def trash_generated(paths):
            for directory in paths:
                expected = {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in directory.rglob("*") if p.is_file()}
                result = subprocess.run([str(helper), str(directory)], check=True, capture_output=True, text=True)
                destination = Path(result.stdout.strip())
                run("record-trash", "--source", directory, "--destination", destination, session=directory.parents[2])
                assert destination.is_dir() and not directory.exists()
                assert destination.name.startswith(directory.name)
                assert destination.parent.name == ".Trash", destination
                assert expected == {str(p.relative_to(destination)): hashlib.sha256(p.read_bytes()).hexdigest()
                                    for p in destination.rglob("*") if p.is_file()}
                # This directory was just created by this test's own Trash call.
                shutil.rmtree(destination)

        trash_generated(originals)
        run("desktop-session", "--discard", session=session)
        assert not session.exists(), "No file catalogue should remain after quit"
        restarted = new_session()
        fresh = run("ui-snapshot", session=restarted)
        assert fresh["latest_plan"] is None and fresh["recent_changes"] == []
        assert fresh["folder_settings"][0]["recipe"]["optimization_settings"]["jpeg_quality"] == 74
        run("desktop-session", "--discard", session=restarted)

        # Simulate a crash after publishing a replacement but before the
        # transaction was recorded complete. Recovery must restore the source
        # before any scratch records can be discarded.
        source.write_bytes(original)
        interrupted = new_session()
        run("analyze-all", session=interrupted)
        run("annual-all", "--yes", session=interrupted)
        committed_databases = []
        for candidate in interrupted.glob("folders/*/media-maintenance.sqlite"):
            with sqlite3.connect(candidate) as con:
                if con.execute("SELECT COUNT(*) FROM commit_items WHERE status='COMMITTED'").fetchone()[0]:
                    committed_databases.append(candidate)
        assert len(committed_databases) == 1, committed_databases
        db = committed_databases[0]
        state = db.parent
        with sqlite3.connect(db) as con:
            con.row_factory = sqlite3.Row
            row = con.execute("SELECT * FROM commit_items WHERE status='COMMITTED'").fetchone()
            cid = row["commit_id"]
            con.execute("UPDATE commits SET status='RUNNING' WHERE commit_id=?", (cid,))
            security.journal_begin(state, photos, cid, source, Path(row["final_path"]),
                                   Path(row["quarantine_path"]), row["source_original_sha256"],
                                   row["final_sha256"], row["operation"])
        recovery = run("desktop-session", session=interrupted)
        assert source.read_bytes() == original
        assert recovery["original_folders"], "Recovered replacements must also be preserved"
        trash_generated([Path(p) for p in recovery["original_folders"]])
        run("desktop-session", "--discard", session=interrupted)
        assert not interrupted.exists()

        # Refuse paths outside the dedicated sessions directory and symlinked
        # sessions; leave all older databases and originals byte-identical.
        run("ui-snapshot", session=base / str(uuid.uuid4()), success=False)
        unsafe = new_session()
        unsafe.symlink_to(legacy_state, target_is_directory=True)
        run("desktop-session", "--discard", session=unsafe, success=False)
        assert legacy_original.read_bytes() == b"An older original must never be discarded."
        assert hashlib.sha256(legacy_db.read_bytes()).hexdigest() == legacy_db_before
    print("Desktop fresh sessions, saved preferences, native Trash, crash recovery, leases and legacy preservation: PASS")


if __name__ == "__main__":
    main()
