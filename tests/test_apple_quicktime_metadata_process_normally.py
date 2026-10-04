#!/usr/bin/env python3

import json
import tempfile
from pathlib import Path

import media_audit as audit
import media_maintenance as mm


APPLE_REASON = "video_source_review:apple_quicktime_metadata_streams:5"


def main():
    # Central safety predicate: exact whitelisted reasons only.
    assert mm.review_reason_allows_process_normally("date_conflict")
    assert mm.review_reason_allows_process_normally("date_low_confidence")
    assert mm.review_reason_allows_process_normally(APPLE_REASON)

    assert not mm.review_reason_allows_process_normally(
        "video_source_review:extra_data_streams:5"
    )
    assert not mm.review_reason_allows_process_normally(
        "video_source_review:variable_frame_rate"
    )
    assert not mm.review_reason_allows_process_normally(
        "video_source_review:apple_quicktime_metadata_streams:5,variable_frame_rate"
    )
    assert not mm.review_reason_allows_process_normally(
        "video_source_review:apple_quicktime_metadata_streams:0"
    )

    # Staging suppression is exact: the approved Apple metadata reason may
    # disappear, but a newly detected safety reason must remain.
    approved_item = {
        "target": {
            "review_resolution": "PROCESS_NORMALLY",
            "review_original_reason": APPLE_REASON,
        }
    }

    assert mm._filter_approved_video_review_reasons(
        approved_item,
        ["apple_quicktime_metadata_streams:5"],
    ) == []

    assert mm._filter_approved_video_review_reasons(
        approved_item,
        [
            "apple_quicktime_metadata_streams:5",
            "variable_frame_rate",
        ],
    ) == ["variable_frame_rate"]

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        root = td / "Media"
        rel = Path("test/IMG_2883.MOV")
        path = root / rel
        path.parent.mkdir(parents=True)
        path.write_bytes(b"apple-metadata-review-test")

        qh = audit.quick_hash(path)
        size = path.stat().st_size

        state = td / "state"
        state.mkdir()
        db = state / "media-maintenance.sqlite"
        con = mm.init_db(db, root)

        run_id = "run-apple-review"
        plan_id = "plan-apple-review"

        con.execute(
            "INSERT INTO runs(run_id,started_at,run_date,cutoff,root,tool_version,status) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                run_id,
                mm.now_iso(),
                "2026-10-04",
                "2025-01-01",
                str(root),
                mm.VERSION,
                "PLANNED",
            ),
        )

        con.execute(
            "INSERT INTO assets("
            "relpath,size,mtime_ns,quick_hash,tags_json,personal_tags_json,"
            "xattrs_json,last_seen_run,active"
            ") VALUES(?,?,?,?,?,?,?,?,1)",
            (
                str(rel),
                size,
                path.stat().st_mtime_ns,
                qh,
                "[]",
                "[]",
                "[]",
                run_id,
            ),
        )

        asset_id = con.execute(
            "SELECT asset_id FROM assets WHERE relpath=?",
            (str(rel),),
        ).fetchone()[0]

        con.execute(
            "INSERT INTO review_resolutions("
            "asset_id,plan_id,review_reason,resolution,decided_at,"
            "source_quick_hash,source_size,details_json"
            ") VALUES(?,?,?,?,?,?,?,?)",
            (
                asset_id,
                plan_id,
                APPLE_REASON,
                "PROCESS_NORMALLY",
                mm.now_iso(),
                qh,
                size,
                json.dumps({"note": "approved Apple metadata removal"}),
            ),
        )
        con.commit()

        item = {
            "asset_id": asset_id,
            "relpath": str(rel),
            "source_quick_hash": qh,
            "source_size": size,
            "operation": "REVIEW",
            "policy_version": "streams-video-handbrake-square-pixel-720p-v4-no-autocrop",
            "reason": APPLE_REASON,
            "target": {
                "preset": "preset-720P.json",
                "container": "mp4",
            },
            "executable": False,
        }

        resolved = mm.apply_historical_review_resolution(con, dict(item))

        assert resolved["operation"] == "CONVERT_VIDEO", resolved
        assert resolved["executable"] is True, resolved
        assert resolved["policy_version"] == item["policy_version"], resolved
        assert resolved["target"]["review_resolution"] == "PROCESS_NORMALLY"
        assert resolved["target"]["review_original_reason"] == APPLE_REASON

        # A changed source cannot inherit the approval.
        changed = dict(item)
        changed["source_quick_hash"] = "changed"
        assert mm.apply_historical_review_resolution(
            con,
            changed,
        )["operation"] == "REVIEW"

        # An arbitrary data-stream review remains non-bypassable even if a
        # malicious/stale PROCESS_NORMALLY row somehow exists in SQLite.
        unsafe_reason = "video_source_review:extra_data_streams:5"
        con.execute(
            "INSERT INTO review_resolutions("
            "asset_id,plan_id,review_reason,resolution,decided_at,"
            "source_quick_hash,source_size,details_json"
            ") VALUES(?,?,?,?,?,?,?,?)",
            (
                asset_id,
                plan_id,
                unsafe_reason,
                "PROCESS_NORMALLY",
                mm.now_iso(),
                qh,
                size,
                "{}",
            ),
        )
        con.commit()

        unsafe = dict(item)
        unsafe["reason"] = unsafe_reason

        assert mm.apply_historical_review_resolution(
            con,
            unsafe,
        )["operation"] == "REVIEW"

        con.close()

    print("Apple QuickTime metadata PROCESS_NORMALLY regression: PASS")


if __name__ == "__main__":
    main()
