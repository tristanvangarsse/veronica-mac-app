#!/usr/bin/env python3

import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image
from fixture_dates import exif_date


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "media_maintenance.py"


def run(args):
    return subprocess.run(
        [sys.executable, str(ENGINE), *args],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT)},
        text=True,
        capture_output=True,
        check=False,
    )


with tempfile.TemporaryDirectory(prefix="veronica-annual-rename-") as tmp:
    base = Path(tmp)
    media = base / "Media"
    state = base / "State"

    folder = media / "Streams" / "Image" / "2023"
    folder.mkdir(parents=True)

    import json
    state.mkdir()
    (state/'settings.json').write_text(json.dumps({"filename_date_format":"YYYY-MM-DD_"}))
    policy=base/'policy.json';policy.write_text(json.dumps({"recompress_images_below_target":False}))
    source = folder / "230101-annual-rename.jpg"
    Image.new("RGB", (100, 100), "white").save(source, "JPEG", exif=exif_date())

    result = run([
        "annual",
        "--root", str(media),
        "--state-dir", str(state),
        "--run-date", "2026-09-22",
        "--rename-batch", "25",
        "--config", str(policy),
        "--yes",
    ])

    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)

    final_path = folder / "2023-01-01_annual-rename.jpg"

    assert not source.exists(), source
    assert final_path.is_file(), final_path

    con = sqlite3.connect(state / "media-maintenance.sqlite")

    row = con.execute("""
        SELECT operation,status,final_path
        FROM commit_items
        WHERE operation='RENAME'
        ORDER BY rowid DESC
        LIMIT 1
    """).fetchone()

    assert row is not None, "missing rename commit"
    assert row[0] == "RENAME", row
    assert row[1] == "COMMITTED", row
    assert Path(row[2]).resolve() == final_path.resolve(), row

    asset = con.execute("""
        SELECT relpath
        FROM assets
        WHERE active=1
    """).fetchone()

    assert asset is not None
    assert asset[0] == "Streams/Image/2023/2023-01-01_annual-rename.jpg", asset

    con.close()

print("annual filename rename regression: PASS")
