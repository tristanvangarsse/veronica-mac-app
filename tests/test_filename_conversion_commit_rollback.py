#!/usr/bin/env python3

import datetime as dt
import json
import os
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from PIL import Image
from fixture_dates import exif_date


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "media_maintenance.py"


def run(args, env=None):
    result = subprocess.run(
        ["python3", str(ENGINE)] + args,
        cwd=ROOT,
        text=True,
        capture_output=True,
        env=env,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise RuntimeError(f"command failed: {' '.join(args)}")
    return result


with tempfile.TemporaryDirectory(prefix="veronica-filename-convert-") as tmp:
    base = Path(tmp)
    media = base / "Media"
    state = base / "State"
    source_dir = media / "Streams" / "Image" / "2023"
    source_dir.mkdir(parents=True)
    state.mkdir(parents=True)

    original_name = "2023-01-01_large image.jpg"
    original_relpath = f"Streams/Image/2023/{original_name}"
    original_path = source_dir / original_name

    # >10 MP so Streams image policy actually converts it.
    im = Image.new("RGB", (4000, 3000), (120, 80, 40))
    im.save(original_path, format="JPEG", quality=95, exif=exif_date())

    # Give filesystem evidence a stable 2023-01-01 date.
    stamp = dt.datetime(2023, 1, 1, 12, 0, 0).timestamp()
    os.utime(original_path, (stamp, stamp))

    run([
        "plan",
        "--root", str(media),
        "--state-dir", str(state),
        "--run-date", "2026-09-22",
    ])

    plans = sorted(state.glob("plan-*.json"))
    assert plans, "plan JSON missing"
    plan_path = plans[-1]
    plan = json.loads(plan_path.read_text())

    item = next(i for i in plan["items"] if i["relpath"] == original_relpath)
    assert item["operation"] == "CONVERT_IMAGE", item
    expected_relpath = "Streams/Image/2023/230101-large-image.jpg"
    assert item["target"]["final_relpath"] == expected_relpath, item

    run([
        "stage",
        "--plan", str(plan_path),
        "--state-dir", str(state),
        "--max-images", "1",
        "--max-videos", "0",
        "--max-audio", "0",
        "--sample-strategy", "first",
    ])

    con = sqlite3.connect(state / "media-maintenance.sqlite")
    staging_id = con.execute(
        "SELECT staging_id FROM staging_runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()[0]
    con.close()

    run([
        "commit",
        "--staging-id", staging_id,
        "--state-dir", str(state),
        "--relpath", original_relpath,
        "--yes",
    ])

    final_path = media / expected_relpath

    assert final_path.is_file(), final_path
    assert not original_path.exists(), original_path

    con = sqlite3.connect(state / "media-maintenance.sqlite")
    row = con.execute("""
        SELECT commit_id, final_path, status
        FROM commit_items
        WHERE relpath=?
        ORDER BY rowid DESC
        LIMIT 1
    """, (original_relpath,)).fetchone()

    assert row, "commit row missing"
    commit_id, recorded_final_path, status = row
    assert status == "COMMITTED", row
    assert Path(recorded_final_path).resolve() == final_path.resolve(), row

    active_relpath = con.execute(
        "SELECT relpath FROM assets WHERE active=1"
    ).fetchone()[0]
    assert active_relpath == expected_relpath, active_relpath
    con.close()

    run([
        "rollback",
        "--commit-id", commit_id,
        "--state-dir", str(state),
        "--yes",
    ])

    assert original_path.is_file(), original_path
    assert not final_path.exists(), final_path

    con = sqlite3.connect(state / "media-maintenance.sqlite")
    status = con.execute(
        "SELECT status FROM commit_items WHERE commit_id=?",
        (commit_id,),
    ).fetchone()[0]
    assert status == "ROLLED_BACK", status

    active_relpath = con.execute(
        "SELECT relpath FROM assets WHERE active=1"
    ).fetchone()[0]
    assert active_relpath == original_relpath, active_relpath
    con.close()

print("filename conversion commit/rollback regression: PASS")
