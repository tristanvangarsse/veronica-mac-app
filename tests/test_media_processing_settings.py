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
    expected_video_extensions = sorted(mm.audit.VIDEO_EXTS)
    assert saved == {
        "images": False,
        "videos": True,
        "audio": False,
        "image_extensions": [],
        "video_extensions": expected_video_extensions,
        "audio_extensions": [],
    }, saved

    settings = json.loads((state / "settings.json").read_text())
    assert settings["process_images"] is False
    assert settings["process_videos"] is True
    assert settings["process_audio"] is False
    assert settings["process_image_extensions"] == []
    assert settings["process_video_extensions"] == expected_video_extensions
    assert settings["process_audio_extensions"] == []

    snap = run(
        "ui-snapshot",
        "--state-dir", str(state),
    )
    payload = json.loads(snap.stdout)
    assert payload["media_processing"] == {
        "images": False,
        "videos": True,
        "audio": False,
        "image_extensions": [],
        "video_extensions": expected_video_extensions,
        "audio_extensions": [],
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
            "extension": ".jpg",
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
            "extension": ".mp4",
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
            "extension": ".wav",
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
    cfg["process_image_extensions"] = sorted(mm.audit.IMAGE_EXTS)
    cfg["process_video_extensions"] = sorted(mm.audit.VIDEO_EXTS)
    cfg["process_audio_extensions"] = sorted(mm.audit.AUDIO_EXTS)

    enabled_video = mm.make_item(rows["video"], 99, cfg)
    assert enabled_video["operation"] == "REVIEW", enabled_video
    assert enabled_video["reason"] == "date_low_confidence", enabled_video
    assert enabled_video["operation"] != "SKIP_MEDIA_TYPE_DISABLED"

    disabled_extension_cfg = json.loads(json.dumps(cfg))
    disabled_extension_cfg["process_video_extensions"] = [".mov"]
    disabled_extension = mm.make_item(rows["video"], 98, disabled_extension_cfg)
    assert disabled_extension["operation"] == "SKIP_EXTENSION_DISABLED", disabled_extension
    assert disabled_extension["reason"] == "video_extension_disabled_by_user", disabled_extension
    assert disabled_extension["target"] == {
        "media_type": "video",
        "extension": ".mp4",
    }, disabled_extension

    # Non-media content is inventoried but is not Veronica maintenance work
    # and must never become executable or user-facing Review noise.
    document_row = {
        "relpath": "example.docx",
        "detected_kind": "unknown",
        "tags": [],
        "action": "REVIEW",
        "reason": "unclassified_content:unknown",
        "quick_hash": "document-hash",
        "size": 4096,
        "mtime_ts": 1,
        "best_date": None,
    }

    document_item = mm.make_item(document_row, 100, cfg)
    document_item = mm.apply_filename_policy(document_item, document_row, cfg)

    assert document_item["operation"] == "SKIP_NONMEDIA", document_item
    assert document_item["executable"] is False, document_item
    assert document_item["reason"] == "unclassified_content:unknown", document_item
    assert "final_relpath" not in document_item["target"], document_item

    # Date-only review should not block optimization when the user is
    # maintaining all dates. It should only suppress date-based renaming.
    uncertain_date_row = {
        "relpath": "ambiguous-date-photo.jpg",
        "detected_kind": "image",
        "tags": [],
        "action": "REVIEW",
        "reason": "date_low_confidence",
        "quick_hash": "uncertain-date-hash",
        "size": 5_000_000,
        "mtime_ts": 1,
        "best_date": "2024-01-02",
        "megapixels": 24.0,
        "animated": False,
        "extension": ".jpg",
        "has_alpha": False,
    }
    all_dates_cfg = json.loads(json.dumps(base_cfg))
    all_dates_cfg["date_scope"] = {"mode": "all"}
    all_dates_cfg["streams_image_max_megapixels"] = 10
    all_dates_cfg["filename_standardization_enabled"] = True

    assert mm.should_auto_optimize_date_review(uncertain_date_row, all_dates_cfg)
    date_item = mm.make_item(
        {**uncertain_date_row, "action": "CANDIDATE"},
        101,
        all_dates_cfg,
    )
    filename_row = {**uncertain_date_row, "best_date": None}
    date_item = mm.apply_filename_policy(date_item, filename_row, all_dates_cfg)

    assert date_item["operation"] == "CONVERT_IMAGE", date_item
    assert "final_relpath" not in date_item["target"], date_item

    ranged_cfg = json.loads(json.dumps(all_dates_cfg))
    ranged_cfg["date_scope"] = {
        "mode": "within",
        "start": "2024-01-01",
        "end": "2024-12-31",
    }
    assert not mm.should_auto_optimize_date_review(uncertain_date_row, ranged_cfg)

    # Managed child-folder state must inherit the global media switches used
    # by annual-all. This is the regression that caused Videos-only runs to
    # behave as though Images and Audio were enabled.
    parent_state = base / "ParentState"
    child_media = base / "ManagedMedia"
    child_media.mkdir()

    parent_settings = {
        "process_images": False,
        "process_videos": True,
        "process_audio": False,
        "process_image_extensions": [],
        "process_video_extensions": [".mp4", ".mov"],
        "process_audio_extensions": [],
        "media_processing_settings_updated_at": "2026-10-04T00:00:00+00:00",
        "scan_folders": [str(child_media)],
    }
    mm.save_product_settings(parent_state, parent_settings)

    child_state = mm.prepare_scan_folder_state(parent_state, child_media)
    child_settings = mm.load_product_settings(child_state)

    assert child_settings["process_images"] is False, child_settings
    assert child_settings["process_videos"] is True, child_settings
    assert child_settings["process_audio"] is False, child_settings
    assert child_settings["process_image_extensions"] == [], child_settings
    assert child_settings["process_video_extensions"] == [".mov", ".mp4"], child_settings
    assert child_settings["process_audio_extensions"] == [], child_settings
    assert (
        child_settings["media_processing_settings_updated_at"]
        == parent_settings["media_processing_settings_updated_at"]
    ), child_settings

    # The native Optimization Recipe is saved at app level too. Managed child
    # state must inherit it before planning, otherwise selected media is
    # analyzed with default image/video/audio targets.
    optimization_parent_state = base / "OptimizationParentState"
    optimization_media = base / "OptimizationManagedMedia"
    optimization_media.mkdir()

    optimization_parent_settings = {
        "scan_folders": [str(optimization_media)],
        "image_output_format": "png",
        "image_max_megapixels": 4.0,
        "jpeg_quality": 82,
        "video_max_edge": 1080,
        "audio_min_size_mb": 42,
        "video_allow_camera_metadata_drop": False,
        "optimization_settings_updated_at": "2026-10-11T00:00:00+00:00",
    }
    mm.save_product_settings(optimization_parent_state, optimization_parent_settings)

    optimization_child_state = mm.prepare_scan_folder_state(
        optimization_parent_state,
        optimization_media,
    )
    optimization_child_settings = mm.load_product_settings(optimization_child_state)

    assert optimization_child_settings["image_output_format"] == "png"
    assert optimization_child_settings["image_max_megapixels"] == 4.0
    assert optimization_child_settings["jpeg_quality"] == 82
    assert optimization_child_settings["video_max_edge"] == 1080
    assert optimization_child_settings["audio_min_size_mb"] == 42
    assert optimization_child_settings["video_allow_camera_metadata_drop"] is False
    assert (
        optimization_child_settings["optimization_settings_updated_at"]
        == optimization_parent_settings["optimization_settings_updated_at"]
    ), optimization_child_settings

    effective_optimization = mm.optimization_product_settings(
        optimization_child_state
    )
    assert effective_optimization == {
        "image_output_format": "png",
        "image_max_megapixels": 4.0,
        "jpeg_quality": 82,
        "video_max_edge": 1080,
        "audio_min_size_mb": 42,
        "video_allow_camera_metadata_drop": False,
    }, effective_optimization

    camera_metadata_probe = {
        "streams": [
            {"codec_type": "video"},
            {"codec_type": "audio"},
            {
                "codec_type": "data",
                "codec_tag_string": "mebx",
                "tags": {"handler_name": "Core Media Metadata"},
            },
        ],
        "chapters": [],
    }
    optimized_probe = {
        "streams": [
            {"codec_type": "video"},
            {"codec_type": "audio"},
        ],
        "chapters": [],
    }

    assert mm.video_source_review_reasons(camera_metadata_probe, mm.DEFAULT_CONFIG) == []
    strict_cfg = json.loads(json.dumps(mm.DEFAULT_CONFIG))
    strict_cfg["video_allow_camera_metadata_drop"] = False
    assert mm.video_source_review_reasons(
        camera_metadata_probe,
        strict_cfg,
    ) == ["apple_quicktime_metadata_streams:1"]
    assert mm.camera_metadata_drop_allowed(
        camera_metadata_probe,
        optimized_probe,
        mm.DEFAULT_CONFIG,
    )
    subtitle_probe = {
        "streams": [
            {"codec_type": "video"},
            {"codec_type": "audio"},
            {"codec_type": "subtitle"},
        ],
        "chapters": [],
    }
    assert not mm.camera_metadata_drop_allowed(
        subtitle_probe,
        optimized_probe,
        mm.DEFAULT_CONFIG,
    )

    effective = mm.media_processing_product_settings(child_state)
    assert effective == {
        "images": False,
        "videos": True,
        "audio": False,
        "image_extensions": [],
        "video_extensions": [".mov", ".mp4"],
        "audio_extensions": [],
    }, effective

print("media processing settings regression: PASS")
