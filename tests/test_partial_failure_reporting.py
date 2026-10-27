#!/usr/bin/env python3
"""A failed batch must report successful commits and expose pending outputs."""
import argparse
import contextlib
import datetime as dt
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from unittest.mock import patch

from PIL import Image
from fixture_dates import exif_date

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import media_maintenance as mm


with tempfile.TemporaryDirectory(prefix="veronica-partial-failure-") as temp:
    base = Path(temp)
    media = base / "Media"
    state = base / "State"
    folder = media / "Streams/Image/2023"
    folder.mkdir(parents=True)
    for name in ("2023-01-01_a.jpg", "2023-01-01_b.jpg"):
        image = folder / name
        Image.new("RGB", (4000, 3000), (90, 60, 30)).save(image, quality=95, exif=exif_date())
        stamp = dt.datetime(2023, 1, 1, 12).timestamp()
        os.utime(image, (stamp, stamp))
    mm.save_product_settings(state, {"archive_root": str(media.resolve()),
                                     "scan_folders": [str(media.resolve())]})
    real_commit = mm.commit_one

    def fail_second(args, quiet=False):
        if args.relpath.endswith("_b.jpg"):
            raise SystemExit("Injected refusal before source mutation")
        return real_commit(args, quiet=quiet)

    args = argparse.Namespace(root=str(media), state_dir=str(state), config=None,
                              run_date="2026-10-15", yes=True, events_jsonl=None,
                              rename_batch=250, image_batch=250, video_batch=25,
                              audio_batch=10)
    try:
        with patch.object(mm, "commit_one", side_effect=fail_second), \
             contextlib.redirect_stdout(io.StringIO()):
            result = mm.cmd_annual(args)
        assert result == 1
        with sqlite3.connect(state / "media-maintenance.sqlite") as con:
            count, saved = con.execute(
                "select count(*), sum(si.saving_bytes) from commit_items ci "
                "join commits c on c.commit_id=ci.commit_id "
                "join staging_items si on si.staging_id=c.staging_id and si.relpath=ci.relpath "
                "where ci.status='COMMITTED'"
            ).fetchone()
        assert count == 1 and saved > 0, (count, saved)
        report = next(state.glob("annual-*.md")).read_text()
        assert "STOPPED_COMMIT_FAILURE" in report
        assert "committed_images=1" in report, report
        assert f"Committed savings in bytes: **{saved:,}**" in report, report
        snapshot = mm._ui_snapshot_for_folder(media.resolve(), state.resolve(), 20)
        assert snapshot["pending_staged_outputs"] == 1, snapshot
        assert snapshot["committed_outputs"] == 1
        assert snapshot["total_saving_bytes"] == saved
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            mm.cmd_ui_snapshot(argparse.Namespace(state_dir=str(state), recent_limit=20))
        assert json.loads(output.getvalue())["pending_staged_outputs"] == 1
    finally:
        mm.close_event_stream()

print("Partial commit failure reporting and pending-output snapshot: PASS")

# An unreadable input is now a file-local skip, but an output verification
# failure must still stop the entire window before any good output is installed.
with tempfile.TemporaryDirectory(prefix="veronica-verification-stop-") as temp:
    base = Path(temp)
    root, state = base / "Media", base / "State"
    root.mkdir()
    for name in ("a.jpg", "b.jpg"):
        Image.new("RGB", (4000, 3000), (100, 90, 70)).save(root / name, quality=95, exif=exif_date())
    originals = {p.name: p.read_bytes() for p in root.iterdir()}
    mm.save_product_settings(state, {"archive_root": str(root), "scan_folders": [str(root)],
                                     "date_scope_mode": "all"})
    real_verify = mm.verify_staged_output

    def reject_output(src, out, item, cfg):
        if src.name == "b.jpg":
            return "FAILED", {"error": "Injected output metadata mismatch"}
        return real_verify(src, out, item, cfg)

    args = argparse.Namespace(root=str(root), state_dir=str(state), config=None,
                              run_date="2026-10-25", yes=True, events_jsonl=None,
                              rename_batch=250, image_batch=250, video_batch=25, audio_batch=10)
    with patch.object(mm, "verify_staged_output", side_effect=reject_output), \
         contextlib.redirect_stdout(io.StringIO()):
        result = mm.cmd_annual(args)
    assert result == 2
    with sqlite3.connect(state / "media-maintenance.sqlite") as con:
        assert con.execute("SELECT COUNT(*) FROM commit_items WHERE status='COMMITTED'").fetchone()[0] == 0
    assert {p.name: p.read_bytes() for p in root.iterdir()} == originals
    mm.close_event_stream()
print("Output verification failures still stop the full staging window without replacing originals: PASS")
