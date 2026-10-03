#!/usr/bin/env python3

import datetime as dt
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "veronica.py"


def run(*args: str) -> subprocess.CompletedProcess:
    result = subprocess.run(
        [sys.executable, str(ENGINE), *args],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(args)}"
        )
    return result


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def latest_plan(state: Path) -> Path:
    snap = json.loads(
        run(
            "ui-snapshot",
            "--state-dir",
            str(state),
        ).stdout
    )
    assert snap["latest_plan"] is not None, snap
    return Path(snap["latest_plan"]["plan_path"])


with tempfile.TemporaryDirectory(prefix="veronica-lifecycle-") as td:
    base = Path(td)
    media = base / "Media"
    state = base / "State"

    media.mkdir()
    state.mkdir()

    image = media / "large-image.jpg"
    Image.new(
        "RGB",
        (4000, 3000),
        (120, 80, 40),
    ).save(
        image,
        format="JPEG",
        quality=95,
    )

    video = media / "large-video.mp4"

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1920x1080:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:sample_rate=48000",
            "-t",
            "3",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            "-shortest",
            str(video),
        ],
        cwd=ROOT,
        check=True,
    )

    audio = media / "large-audio.wav"

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anoisesrc=color=pink:sample_rate=44100",
            "-t",
            "150",
            "-c:a",
            "pcm_s16le",
            str(audio),
        ],
        cwd=ROOT,
        check=True,
    )

    stamp = dt.datetime(
        2023,
        1,
        15,
        12,
        0,
        0,
    ).timestamp()

    for path in (image, video, audio):
        os.utime(path, (stamp, stamp))

    original_hashes = {
        path.name: sha256(path)
        for path in (image, video, audio)
    }

    run(
        "configure-library",
        "--state-dir",
        str(state),
        "--root",
        str(media),
    )

    run(
        "plan",
        "--root",
        str(media),
        "--state-dir",
        str(state),
        "--run-date",
        "2026-10-03",
    )

    review_plan = latest_plan(state)
    review_data = json.loads(review_plan.read_text())

    assert len(review_data["items"]) == 3
    assert all(
        item["operation"] == "REVIEW"
        for item in review_data["items"]
    )

    for name in (
        "large-image.jpg",
        "large-video.mp4",
        "large-audio.wav",
    ):
        run(
            "resolve-review",
            "--state-dir",
            str(state),
            "--plan",
            str(review_plan),
            "--relpath",
            name,
            "--resolution",
            "PROCESS_NORMALLY",
            "--note",
            "Automated lifecycle regression.",
            "--yes",
        )

    for path in (image, video, audio):
        assert sha256(path) == original_hashes[path.name]

    run(
        "plan",
        "--root",
        str(media),
        "--state-dir",
        str(state),
        "--run-date",
        "2026-10-03",
    )

    plan = latest_plan(state)
    data = json.loads(plan.read_text())

    operations = {
        item["relpath"]: item["operation"]
        for item in data["items"]
    }

    assert operations == {
        "large-image.jpg": "CONVERT_IMAGE",
        "large-video.mp4": "CONVERT_VIDEO",
        "large-audio.wav": "CONVERT_AUDIO",
    }, operations

    run(
        "stage",
        "--plan",
        str(plan),
        "--state-dir",
        str(state),
        "--max-images",
        "1",
        "--max-videos",
        "1",
        "--max-audio",
        "1",
        "--sample-strategy",
        "first",
    )

    con = sqlite3.connect(
        state / "media-maintenance.sqlite"
    )

    staging_id = con.execute(
        """
        SELECT staging_id
        FROM staging_runs
        WHERE plan_id=?
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (data["plan_id"],),
    ).fetchone()[0]

    staged = con.execute(
        """
        SELECT relpath, operation, status
        FROM staging_items
        WHERE staging_id=?
        ORDER BY relpath
        """,
        (staging_id,),
    ).fetchall()

    con.close()

    assert staged == [
        ("large-audio.wav", "CONVERT_AUDIO", "STAGED_VERIFIED"),
        ("large-image.jpg", "CONVERT_IMAGE", "STAGED_VERIFIED"),
        ("large-video.mp4", "CONVERT_VIDEO", "STAGED_VERIFIED"),
    ], staged

    for path in (image, video, audio):
        assert path.is_file()
        assert sha256(path) == original_hashes[path.name]

    run(
        "commit",
        "--staging-id",
        staging_id,
        "--state-dir",
        str(state),
        "--relpath",
        "large-image.jpg",
        "--yes",
    )

    run(
        "commit-video",
        "--staging-id",
        staging_id,
        "--state-dir",
        str(state),
        "--relpath",
        "large-video.mp4",
        "--yes",
    )

    run(
        "commit-audio",
        "--staging-id",
        staging_id,
        "--state-dir",
        str(state),
        "--relpath",
        "large-audio.wav",
        "--yes",
    )

    final_image = media / "2023-01-15_large-image.jpg"
    final_video = media / "2023-01-15_large-video.mp4"
    final_audio = media / "2023-01-15_large-audio.mp3"

    assert final_image.is_file()
    assert final_video.is_file()
    assert final_audio.is_file()

    assert not image.exists()
    assert not video.exists()
    assert not audio.exists()

    con = sqlite3.connect(
        state / "media-maintenance.sqlite"
    )

    rows = con.execute(
        """
        SELECT relpath, operation, status, commit_id
        FROM commit_items
        WHERE status='COMMITTED'
        ORDER BY relpath
        """
    ).fetchall()

    con.close()

    assert [r[:3] for r in rows] == [
        ("large-audio.wav", "CONVERT_AUDIO", "COMMITTED"),
        ("large-image.jpg", "CONVERT_IMAGE", "COMMITTED"),
        ("large-video.mp4", "CONVERT_VIDEO", "COMMITTED"),
    ], rows

    commit_ids = {
        relpath: commit_id
        for relpath, _, _, commit_id in rows
    }

    snap = json.loads(
        run(
            "ui-snapshot",
            "--state-dir",
            str(state),
        ).stdout
    )

    assert snap["committed_outputs"] == 3, snap
    assert snap["latest_plan"]["remaining_executable_count"] == 0, snap

    for relpath in (
        "large-audio.wav",
        "large-video.mp4",
        "large-image.jpg",
    ):
        run(
            "rollback",
            "--commit-id",
            commit_ids[relpath],
            "--state-dir",
            str(state),
            "--yes",
        )

    for path in (image, video, audio):
        assert path.is_file(), path
        assert sha256(path) == original_hashes[path.name], path

    assert not final_image.exists()
    assert not final_video.exists()
    assert not final_audio.exists()

    snap = json.loads(
        run(
            "ui-snapshot",
            "--state-dir",
            str(state),
        ).stdout
    )

    assert snap["committed_outputs"] == 0, snap
    assert snap["rolled_back_outputs"] == 3, snap
    assert snap["latest_plan"]["remaining_executable_count"] == 3, snap

print("media lifecycle end-to-end regression: PASS")
