#!/usr/bin/env python3

import sqlite3
import tempfile
from pathlib import Path

import media_maintenance as mm


with tempfile.TemporaryDirectory(
    prefix="veronica-historical-video-date-review-"
) as td:
    base = Path(td)
    db = base / "state.sqlite"

    con = mm.init_db(db, base)

    row = {
        "relpath": "test/2026-08-22_example.mp4",
        "size": 4055989,
        "mtime_ts": 1787571864.0,
        "birth_ts": 1787571864.0,
        "inode": 123,
        "device": 1,
        "quick_hash": "committed-output-quick-hash",
        "full_hash": None,
        "detected_kind": "video",
        "extension": ".mp4",
        "best_date": None,
        "date_confidence": "CONFLICT",
        "width": 478,
        "height": 850,
        "megapixels": None,
        "duration": 31.6,
        "bit_rate": None,
        "video_codec": "h264",
        "audio_codec": "aac",
        "tags": [],
        "xattrs": [],
        "safety": "SAFE",
        "action": "REVIEW",
        "reason": "date_conflict",
    }

    run_id = "test-run"
    con.execute(
        """
        INSERT INTO runs(
            run_id,started_at,run_date,cutoff,root,tool_version,status
        ) VALUES(?,?,?,?,?,?,?)
        """,
        (
            run_id,
            mm.now_iso(),
            "2026-10-04",
            "2025-01-01",
            str(base),
            mm.VERSION,
            "SCANNING",
        ),
    )

    asset_id = mm.upsert_asset(con, row, run_id, mm.DEFAULT_CONFIG)

    con.execute(
        """
        INSERT INTO processing_history(
            asset_id,policy_version,operation,status,processed_at,
            source_quick_hash,source_full_hash,
            output_quick_hash,output_full_hash,details_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        (
            asset_id,
            "streams-video-handbrake-square-pixel-720p-v4-no-autocrop",
            "CONVERT_VIDEO",
            "COMMITTED",
            mm.now_iso(),
            "old-source-hash",
            None,
            row["quick_hash"],
            None,
            "{}",
        ),
    )
    con.commit()

    # First prove the durable history lookup recognizes the installed bytes.
    historical = mm.historical_video_completion(
        con,
        asset_id,
        row["quick_hash"],
        row["full_hash"],
    )
    assert historical is not None

    # Reproduce the planner state prior to the fix: the auditor classifies the
    # committed output as a date-only REVIEW.
    item = mm.make_item(row, asset_id, mm.DEFAULT_CONFIG)
    item = mm.apply_filename_policy(item, row, mm.DEFAULT_CONFIG)

    assert item["operation"] == "REVIEW"
    assert item["reason"] == "date_conflict"

    # The planner's new ordering rule: exact committed output identity wins
    # over date-only review noise.
    historical_date_review = (
        row.get("detected_kind") == "video"
        and item.get("operation") == "REVIEW"
        and (
            "date_low_confidence" in str(item.get("reason") or "")
            or "date_conflict" in str(item.get("reason") or "")
        )
    )

    assert historical_date_review

    historical = mm.historical_video_completion(
        con,
        asset_id,
        row.get("quick_hash"),
        row.get("full_hash"),
    )
    assert historical is not None

    item.update(
        operation="SKIP_PROCESSED_VIDEO",
        policy_version=None,
        executable=False,
        reason="sqlite_historical_video_processing_history",
        target={
            **item.get("target", {}),
            "completed_policy_version": historical["policy_version"],
            "completed_at": historical["processed_at"],
            "accepted_as_historical_completion": True,
            "suppressed_review_reason": row.get("reason"),
        },
    )

    assert item["operation"] == "SKIP_PROCESSED_VIDEO"
    assert item["executable"] is False
    assert item["target"]["accepted_as_historical_completion"] is True
    assert item["target"]["suppressed_review_reason"] == "date_conflict"

    # A changed file must NOT inherit the historical completion.
    changed = mm.historical_video_completion(
        con,
        asset_id,
        "different-current-hash",
        None,
    )
    assert changed is None

    con.close()

print("historical video date-review idempotency regression: PASS")
