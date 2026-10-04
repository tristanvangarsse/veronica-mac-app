#!/usr/bin/env python3

import media_maintenance as mm


cfg = dict(mm.DEFAULT_CONFIG)

iphone_video = {
    "streams": [
        {
            "index": 0,
            "codec_type": "audio",
            "codec_name": "aac",
            "channels": 2,
        },
        {
            "index": 1,
            "codec_type": "video",
            "codec_name": "h264",
            "width": 568,
            "height": 320,
            "avg_frame_rate": "30/1",
            "r_frame_rate": "30/1",
        },
        *[
            {
                "index": i,
                "codec_type": "data",
                "codec_tag_string": "mebx",
                "tags": {
                    "handler_name": "Core Media Metadata",
                    "language": "und",
                },
            }
            for i in range(2, 7)
        ],
    ],
    "chapters": [],
    "format": {
        "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
        "tags": {
            "com.apple.quicktime.make": "Apple",
            "com.apple.quicktime.model": "iPhone 17 Pro Max",
        },
    },
}

reasons = mm.video_source_review_reasons(iphone_video, cfg)

assert "apple_quicktime_metadata_streams:5" in reasons, reasons
assert "extra_data_streams:5" not in reasons, reasons

unknown_data = {
    **iphone_video,
    "streams": [
        *iphone_video["streams"][:2],
        {
            "index": 2,
            "codec_type": "data",
            "codec_tag_string": "abcd",
            "tags": {"handler_name": "Unknown Data"},
        },
    ],
}

reasons = mm.video_source_review_reasons(unknown_data, cfg)

assert "extra_data_streams:1" in reasons, reasons
assert not any(
    reason.startswith("apple_quicktime_metadata_streams:")
    for reason in reasons
), reasons

mixed_data = {
    **iphone_video,
    "streams": [
        *iphone_video["streams"][:2],
        {
            "index": 2,
            "codec_type": "data",
            "codec_tag_string": "mebx",
            "tags": {"handler_name": "Core Media Metadata"},
        },
        {
            "index": 3,
            "codec_type": "data",
            "codec_tag_string": "abcd",
            "tags": {"handler_name": "Unknown Data"},
        },
    ],
}

reasons = mm.video_source_review_reasons(mixed_data, cfg)

assert "extra_data_streams:2" in reasons, reasons
assert not any(
    reason.startswith("apple_quicktime_metadata_streams:")
    for reason in reasons
), reasons

print("Apple QuickTime metadata stream classification regression: PASS")
