#!/usr/bin/env python3
"""Scan progress must reflect the same read-only inventory as a normal scan."""

import datetime as dt
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

import media_audit as audit


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="veronica-scan-progress-") as td:
        base = Path(td).resolve()
        media = base / "Media"
        empty = base / "Empty"
        outside = base / "Outside"
        state = base / "State"
        for folder in (media, empty, outside):
            folder.mkdir()
        (media / "Nested").mkdir()
        (media / "2020-01-01_photo.jpg").write_bytes(b"")
        (media / "Nested" / "notes.txt").write_text("original content")
        (media / ".DS_Store").write_bytes(b"ignored")
        (outside / "private.txt").write_text("must not be followed")
        (media / "Linked folder").symlink_to(outside, target_is_directory=True)

        cfg = dict(audit.DEFAULT_CONFIG)
        run_date = dt.date(2026, 10, 15)
        normal = audit.Auditor(media, cfg, run_date, base / "Audit", False, False)
        normal.walk()
        tracked = audit.Auditor(media, cfg, run_date, base / "Audit", False, False)
        updates = []
        tracked.walk(on_progress=lambda done, total: updates.append((done, total)))
        assert updates == [(0, 3), (1, 3), (2, 3), (3, 3)], updates
        assert tracked.rows == normal.rows
        assert tracked.issues == normal.issues

        def run(*args):
            result = subprocess.run(
                [sys.executable, str(PROJECT / "media_maintenance.py"), *args],
                cwd=PROJECT, capture_output=True, text=True,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            return result

        run("configure-folders", "--state-dir", str(state),
            "--add", str(media), "--add", str(empty))
        events = base / "progress.jsonl"
        run("analyze-all", "--state-dir", str(state),
            "--run-date", "2026-10-15", "--events-jsonl", str(events))
        rows = [json.loads(line) for line in events.read_text().splitlines()]
        assert rows and all(row["event"] == "analysis_progress" for row in rows), rows
        for folder, total in ((media, 3), (empty, 0)):
            progress = [row for row in rows if row["folder"] == str(folder)]
            assert progress[0]["phase"] == "discovering", progress
            assert progress[0]["total_files"] is None
            assert progress[-1]["phase"] == "planning", progress
            assert all(row["folder_count"] == 2 for row in progress)
            scans = [row for row in progress if row["phase"] == "scanning"]
            assert scans[0]["completed_files"] == 0, scans
            assert scans[-1]["completed_files"] == total, scans
            assert all(row["total_files"] == total for row in scans)
            assert [row["completed_files"] for row in scans] == sorted(
                row["completed_files"] for row in scans
            )
        assert {row["folder_index"] for row in rows} == {1, 2}
        assert (media / "Nested" / "notes.txt").read_text() == "original content"
        assert (media / "2020-01-01_photo.jpg").read_bytes() == b""
        assert (media / "Linked folder").is_symlink()

        # The existing command remains usable without a progress stream.
        run("analyze-all", "--state-dir", str(state), "--run-date", "2026-10-15")

    print("Folder scan progress regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
