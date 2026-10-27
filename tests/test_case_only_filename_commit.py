#!/usr/bin/env python3
"""Case-only conversions must commit and roll back without overwriting aliases."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

from PIL import Image
from fixture_dates import exif_date

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import media_maintenance as mm


def run(*args):
    result = subprocess.run([sys.executable, str(ROOT / "media_maintenance.py"), *args],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


with tempfile.TemporaryDirectory(prefix="veronica-case-only-") as temp:
    base = Path(temp)
    media = base / "Media"
    state = base / "State"
    folder = media / "Streams/Image/2023"
    folder.mkdir(parents=True)
    mm.save_product_settings(state, {"filename_date_format":"YYYY-MM-DD_"})
    source = folder / "2023-01-01_case.JPG"
    Image.new("RGB", (4000, 3000), (100, 60, 30)).save(source, quality=95, exif=exif_date())
    stamp = dt.datetime(2023, 1, 1, 12).timestamp()
    os.utime(source, (stamp, stamp))
    original_hash = mm.sha256_file(source)
    target = source.with_suffix(".jpg")
    assert not mm.destination_is_occupied(source, target)

    other = folder / "unrelated.jpg"
    other.write_bytes(b"keep this file")
    assert mm.destination_is_occupied(source, other)
    hardlink = folder / "hardlink.JPG"
    os.link(source, hardlink)
    assert mm.destination_is_occupied(source, hardlink)
    hardlink.unlink()
    broken_link = folder / "broken.jpg"
    broken_link.symlink_to(folder / "missing")
    assert mm.destination_is_occupied(source, broken_link)
    broken_link.unlink()
    other.unlink()

    # Two differently named hard links that happen to differ only in case
    # must still count as separate destinations on a case-sensitive volume.
    if not target.exists():
        os.link(source, target)
        assert mm.destination_is_occupied(source, target)
        target.unlink()

    run("plan", "--root", str(media), "--state-dir", str(state),
        "--run-date", "2026-10-15")
    plan_path = next(state.glob("plan-*.json"))
    plan = json.loads(plan_path.read_text())
    item = plan["items"][0]
    assert item["operation"] == "CONVERT_IMAGE", item
    assert item["target"]["final_relpath"].endswith("2023-01-01_case.jpg"), item
    run("stage", "--plan", str(plan_path), "--state-dir", str(state),
        "--max-images", "1", "--max-videos", "0", "--max-audio", "0")
    with sqlite3.connect(state / "media-maintenance.sqlite") as con:
        staging_id = con.execute("select staging_id from staging_runs").fetchone()[0]
    run("commit", "--state-dir", str(state), "--staging-id", staging_id,
        "--relpath", item["relpath"], "--yes")
    assert target.is_file()
    assert target.name in os.listdir(folder)
    assert source.name not in os.listdir(folder)
    with sqlite3.connect(state / "media-maintenance.sqlite") as con:
        commit_id, quarantine, final_hash = con.execute(
            "select commit_id, quarantine_path, final_sha256 from commit_items"
        ).fetchone()
    assert mm.sha256_file(Path(quarantine)) == original_hash
    assert mm.sha256_file(target) == final_hash
    run("rollback", "--state-dir", str(state), "--commit-id", commit_id, "--yes")
    assert source.name in os.listdir(folder)
    assert target.name not in os.listdir(folder)
    assert mm.sha256_file(source) == original_hash

print("Case-only filename conversion and rollback: PASS")
