#!/usr/bin/env python3

import tempfile
from pathlib import Path
from unittest.mock import patch

import media_maintenance as mm


APPLE_REASON = "video_source_review:apple_quicktime_metadata_streams:5"


def probe_source():
    return {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 568,
                "height": 320,
                "sample_aspect_ratio": None,
                "display_aspect_ratio": None,
                "avg_frame_rate": "30/1",
                "r_frame_rate": "30/1",
                "tags": {"creation_time": "2025-11-25T08:14:02.000000Z"},
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "channels": 2,
                "sample_rate": "44100",
            },
            *[
                {
                    "codec_type": "data",
                    "codec_tag_string": "mebx",
                    "tags": {"handler_name": "Core Media Metadata"},
                }
                for _ in range(5)
            ],
        ],
        "chapters": [],
        "format": {
            "duration": "16.605",
            "tags": {"creation_time": "2025-11-25T08:14:02.000000Z"},
        },
    }


def probe_output():
    return {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 568,
                "height": 320,
                "sample_aspect_ratio": "1:1",
                "display_aspect_ratio": "71:40",
                "avg_frame_rate": "30/1",
                "r_frame_rate": "30/1",
                "tags": {"creation_time": "2025-11-25T08:14:02.000000Z"},
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "channels": 2,
                "sample_rate": "44100",
            },
        ],
        "chapters": [],
        "format": {
            "duration": "16.605",
            "tags": {"creation_time": "2025-11-25T08:14:02.000000Z"},
        },
    }


def main():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        src = td / "source.mov"
        out = td / "output.mp4"
        src.write_bytes(b"x" * 2_000_000)
        out.write_bytes(b"x" * 1_000_000)

        item = {
            "operation": "CONVERT_VIDEO",
            "target": {
                "review_resolution": "PROCESS_NORMALLY",
                "review_original_reason": APPLE_REASON,
            },
        }

        cfg = dict(mm.DEFAULT_CONFIG)
        cfg["require_creation_date_before_commit"] = False
        cfg["stage_copy_personal_finder_tags"] = False

        probes = [probe_source(), probe_output()]

        with patch.object(mm, "ffprobe_json", side_effect=probes), \
             patch.object(mm, "filesystem_metadata", return_value={
                 "mtime_ns": 0,
                 "birth_ts": 0,
             }), \
             patch.object(mm, "read_finder_tags_safe", return_value=[]):
            status, verification = mm.verify_staged_output(
                src,
                out,
                item,
                cfg,
            )

        assert status == "STAGED_VERIFIED", (status, verification)
        assert verification["stream_counts_preserved"] is False
        assert verification["approved_apple_metadata_stream_drop"] is True

        # Without the exact guarded approval, the same stream loss must fail.
        item["target"] = {}

        probes = [probe_source(), probe_output()]

        with patch.object(mm, "ffprobe_json", side_effect=probes), \
             patch.object(mm, "filesystem_metadata", return_value={
                 "mtime_ns": 0,
                 "birth_ts": 0,
             }), \
             patch.object(mm, "read_finder_tags_safe", return_value=[]):
            status, verification = mm.verify_staged_output(
                src,
                out,
                item,
                cfg,
            )

        assert status == "FAILED"
        assert verification["error"] == "stream_counts_changed"

    print("Apple QuickTime metadata output verification regression: PASS")


if __name__ == "__main__":
    main()
