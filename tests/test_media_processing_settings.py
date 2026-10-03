#!/usr/bin/env python3

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import media_maintenance as mm
ENGINE = ROOT / "media_maintenance.py"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", str(ENGINE), *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def assert_disabled_item(kind: str, item: dict) -> None:
    assert item["operation"] == "SKIP_MEDIA_TYPE_DISABLED", item
    assert item["executable"] is False, item
    assert item["reason"] == f"{kind}_processing_disabled_by_user", item
    assert item["target"] == {"media_type": kind}, item
    assert "final_relpath" not in item["target"], item


with tempfile.TemporaryDirectory(prefix="veronica-media-processing-settings-") as td:
    base = Path(td)
    state = base / "State"
    media = base / "Media"
    media.mkdir()

    # Persistence and snapshot exposure.
    result = run(
        "configure-media-types",
        "--state-dir", str(state),
        "--images", "false",
        "--videos", "true",
        "--audio", "false",
    )

    saved = json.loads(result.stdout)
    assert saved == {
        "images": False,
        "videos": True,
        "audio": False,
    }, saved

    settings = json.loads((state / "settings.json").read_text())
    assert settings["process_images"] is False
    assert settings["process_videos"] is True
    assert settings["process_audio"] is False

    snap = run(
        "ui-snapshot",
        "--state-dir", str(state),
    )
    payload = json.loads(snap.stdout)
    assert payload["media_processing"] == {
        "images": False,
        "videos": True,
        "audio": False,
    }, payload["media_processing"]

    # Planner hard-boundary behavior. Use synthetic planner rows so this test
    # exercises media-type policy directly without depending on ffmpeg, Pillow,
    # filesystem date evidence, or probe behavior.
    base_cfg = json.loads(json.dumps(mm.DEFAULT_CONFIG))
    base_cfg["filename_standardization_enabled"] = True

    rows = {
        "image": {
            "relpath": "test-image.jpg",
            "detected_kind": "image",
            "tags": [],
            "action": "REVIEW",
            "reason": "date_low_confidence",
            "quick_hash": "image-hash",
            "size": 1000,
            "mtime_ts": 1,
            "best_date": "2020-01-01",
        },
        "video": {
            "relpath": "test-video.mp4",
            "detected_kind": "video",
            "tags": [],
            "action": "REVIEW",
            "reason": "date_low_confidence",
            "quick_hash": "video-hash",
            "size": 2000,
            "mtime_ts": 1,
            "best_date": "2020-01-01",
        },
        "audio": {
            "relpath": "test-audio.wav",
            "detected_kind": "audio",
            "tags": [],
            "action": "REVIEW",
            "reason": "date_low_confidence",
            "quick_hash": "audio-hash",
            "size": 3000,
            "mtime_ts": 1,
            "best_date": "2020-01-01",
        },
    }

    for index, kind in enumerate(("image", "video", "audio"), 1):
        cfg = json.loads(json.dumps(base_cfg))
        cfg["process_images"] = kind != "image"
        cfg["process_videos"] = kind != "video"
        cfg["process_audio"] = kind != "audio"

        item = mm.make_item(rows[kind], index, cfg)
        item = mm.apply_filename_policy(item, rows[kind], cfg)

        assert_disabled_item(kind, item)

    # Re-enabling must return the item to ordinary planner behavior.
    cfg = json.loads(json.dumps(base_cfg))
    cfg["process_images"] = True
    cfg["process_videos"] = True
    cfg["process_audio"] = True

    enabled_video = mm.make_item(rows["video"], 99, cfg)
    assert enabled_video["operation"] == "REVIEW", enabled_video
    assert enabled_video["reason"] == "date_low_confidence", enabled_video
    assert enabled_video["operation"] != "SKIP_MEDIA_TYPE_DISABLED"

print("media processing settings regression: PASS")
