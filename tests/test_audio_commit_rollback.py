#!/usr/bin/env python3

import datetime as dt
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "veronica.py"


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)

    result = subprocess.run(
        [sys.executable, str(ENGINE), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )

    if check and result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise RuntimeError(
            f"command failed ({result.returncode}): "
            + " ".join([sys.executable, str(ENGINE), *args])
        )

    return result


def sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


with tempfile.TemporaryDirectory(prefix="veronica-audio-rollback-") as td:
    base = Path(td)
    media = base / "Media"
    state = base / "State"
    media.mkdir()
    state.mkdir()

    source = media / "large-audio.wav"

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
            str(source),
        ],
        check=True,
    )

    stamp = dt.datetime(2023, 1, 15, 12, 0, 0).timestamp()
    os.utime(source, (stamp, stamp))

    original_hash = sha256(source)

    run(
        "configure-library",
        "--state-dir",
        str(state),
        "--root",
        str(media),
    )

    # Initial plan should require a human date resolution for this synthetic file.
    run(
        "plan",
        "--root",
        str(media),
        "--state-dir",
        str(state),
        "--run-date",
        "2026-10-03",
    )

    first_plan = sorted(state.glob("plan-*.json"))[-1]
    first_data = json.loads(first_plan.read_text())
    first_item = next(
        i for i in first_data["items"] if i["relpath"] == source.name
    )

    assert first_item["operation"] == "REVIEW", first_item
    assert "date_low_confidence" in first_item["reason"], first_item

    run(
        "resolve-review",
        "--plan",
        str(first_plan),
        "--state-dir",
        str(state),
        "--relpath",
        source.name,
        "--resolution",
        "PROCESS_NORMALLY",
        "--note",
        "Automated regression fixture",
        "--yes",
    )

    # Re-plan after review resolution.
    run(
        "plan",
        "--root",
        str(media),
        "--state-dir",
        str(state),
        "--run-date",
        "2026-10-03",
    )

    snapshot = json.loads(
        run(
            "ui-snapshot",
            "--state-dir",
            str(state),
        ).stdout
    )

    assert snapshot["latest_plan"] is not None, snapshot
    plan = Path(snapshot["latest_plan"]["plan_path"])
    data = json.loads(plan.read_text())
    item = next(i for i in data["items"] if i["relpath"] == source.name)

    assert item["operation"] == "CONVERT_AUDIO", item
    assert item["executable"] is True, item
    assert item["policy_version"] == "streams-audio-mp3-128k-v1", item

    expected_final = media / item["target"]["final_relpath"]
    assert expected_final.name.endswith(".mp3")

    run(
        "stage",
        "--plan",
        str(plan),
        "--state-dir",
        str(state),
        "--max-images",
        "0",
        "--max-videos",
        "0",
        "--max-audio",
        "1",
        "--sample-strategy",
        "first",
    )

    staging_json = sorted(state.glob("staging-*.json"))[-1]
    staging = json.loads(staging_json.read_text())
    staging_id = staging["staging_id"]

    staged = next(
        r for r in staging["results"] if r["relpath"] == source.name
    )
    assert staged["operation"] == "CONVERT_AUDIO", staged
    assert staged["status"] == "STAGED_VERIFIED", staged
    assert staged["verification"]["metadata_ready_for_commit"] is True, staged

    # Staging must never mutate the source.
    assert source.is_file()
    assert sha256(source) == original_hash

    commit = run(
        "commit-audio",
        "--staging-id",
        staging_id,
        "--state-dir",
        str(state),
        "--relpath",
        source.name,
        "--yes",
    )

    assert "COMMITTED:" in commit.stdout
    assert not source.exists()
    assert expected_final.is_file()

    con = sqlite3.connect(state / "media-maintenance.sqlite")
    row = con.execute(
        """
        SELECT commit_id, status, quarantine_path, final_path
        FROM commit_items
        WHERE relpath=? AND operation='CONVERT_AUDIO'
        ORDER BY rowid DESC
        LIMIT 1
        """,
        (source.name,),
    ).fetchone()
    con.close()

    assert row is not None
    commit_id, status, quarantine_path, final_path = row
    assert status == "COMMITTED"
    assert Path(final_path).resolve() == expected_final.resolve()

    quarantine = Path(quarantine_path)
    assert quarantine.is_file()
    assert sha256(quarantine) == original_hash

    run(
        "rollback",
        "--commit-id",
        commit_id,
        "--state-dir",
        str(state),
        "--yes",
    )

    assert source.is_file()
    assert sha256(source) == original_hash
    assert not expected_final.exists()

    con = sqlite3.connect(state / "media-maintenance.sqlite")
    status = con.execute(
        """
        SELECT status
        FROM commit_items
        WHERE commit_id=?
        """,
        (commit_id,),
    ).fetchone()[0]
    con.close()

    assert status == "ROLLED_BACK"

print("audio commit/rollback regression: PASS")
