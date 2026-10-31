from pathlib import Path

import media_maintenance as mm


def cfg(**overrides):
    out = dict(mm.DEFAULT_CONFIG)
    out.update({
        "filename_standardization_enabled": True,
        "filename_date_format": "YYYY-MM-DD_",
        "filename_max_bytes": 180,
    })
    out.update(overrides)
    return out


# ----------------------------------------------------------------------
# Basic canonical naming
# ----------------------------------------------------------------------

name = mm.canonical_media_filename(
    "Streams/Image/2023/Screenshot 3.png",
    "2023-01-01",
    None,
    cfg(),
)
assert name == "2023-01-01_Screenshot 3.png", name


# Existing canonical prefix must be replaced, not doubled.
name = mm.canonical_media_filename(
    "Streams/Image/2023/2022-12-31_Screenshot 3.png",
    "2023-01-01",
    None,
    cfg(),
)
assert name == "2023-01-01_Screenshot 3.png", name


# Conversion may deliberately change extension.
name = mm.canonical_media_filename(
    "Streams/Image/2023/Test Image 1.png",
    "2023-01-01",
    ".jpg",
    cfg(),
)
assert name == "2023-01-01_Test Image 1.jpg", name


# No trusted resolved date means no rename proposal.
assert mm.canonical_media_filename(
    "Streams/Image/2023/Screenshot.png",
    None,
    None,
    cfg(),
) is None


# Disabled policy must do nothing.
assert mm.canonical_media_filename(
    "Streams/Image/2023/Screenshot.png",
    "2023-01-01",
    None,
    cfg(filename_standardization_enabled=False),
) is None


# ----------------------------------------------------------------------
# UTF-8 byte limit
# ----------------------------------------------------------------------

long_name = "é" * 200 + ".jpg"

name = mm.canonical_media_filename(
    f"Streams/Image/2023/{long_name}",
    "2023-01-01",
    None,
    cfg(filename_max_bytes=80),
)

assert name is not None
assert len(name.encode("utf-8")) <= 80, (
    len(name.encode("utf-8")),
    name,
)
assert name.startswith("2023-01-01_")
assert name.endswith(".jpg")


# ----------------------------------------------------------------------
# Plan-item policy
# ----------------------------------------------------------------------

# Turning off date/name standardization must still give converted content its
# real format extension. JPEG aliases stay unchanged, and disabled types never
# become executable solely to fix a suffix.
for relpath, operation, kind, target, expected in [
    ("Unchanged Stem.png", "CONVERT_IMAGE", "image", {"format": "jpeg"}, "Unchanged Stem.jpg"),
    ("photo.jpg", "CONVERT_IMAGE", "image", {"format": "png"}, "photo.png"),
    ("movie.mov", "CONVERT_VIDEO", "video", {}, "movie.mp4"),
    ("sound.wav", "CONVERT_AUDIO", "audio", {}, "sound.mp3"),
    ("photo.jpeg", "CONVERT_IMAGE", "image", {"format": "jpeg"}, None),
    ("leave.png", "SKIP_EXTENSION_DISABLED", "image", {}, None),
]:
    converted = mm.apply_filename_policy(
        {"relpath": relpath, "operation": operation, "target": target},
        {"relpath": relpath, "detected_kind": kind, "best_date": "2023-01-01"},
        cfg(filename_standardization_enabled=False),
    )
    assert converted["operation"] == operation
    assert converted["target"].get("final_relpath") == expected, converted

row = {
    "relpath": "Streams/Image/2023/Screenshot 3.png",
    "best_date": "2023-01-01",
    "detected_kind": "image",
}

item = {
    "relpath": row["relpath"],
    "operation": "SKIP_NO_BENEFIT",
    "policy_version": None,
    "reason": "image_at_or_below_target",
    "target": {"max_megapixels": 10.0},
    "executable": False,
}

result = mm.apply_filename_policy(dict(item), row, cfg())

assert result["operation"] == "RENAME", result
assert result["executable"] is True, result
assert result["policy_version"] == "filename-standardization-v1", result
assert result["target"]["final_relpath"] == (
    "Streams/Image/2023/2023-01-01_Screenshot 3.png"
), result


# A conversion remains a conversion, but receives its final canonical path.
convert = {
    "relpath": "Streams/Image/2023/Large PNG.png",
    "operation": "CONVERT_IMAGE",
    "policy_version": "streams-image-10mp-v1",
    "reason": "streams_image_above_target",
    "target": {
        "max_megapixels": 10.0,
        "format": "jpeg",
    },
    "executable": True,
}

result = mm.apply_filename_policy(dict(convert), {
    "relpath": convert["relpath"],
    "best_date": "2021-05-06",
    "detected_kind": "image",
}, cfg())

assert result["operation"] == "CONVERT_IMAGE", result
assert result["target"]["final_relpath"] == (
    "Streams/Image/2023/2021-05-06_Large PNG.jpg"
), result


# Safety decisions are not made executable merely for naming.
for operation in ("REVIEW", "PRESERVE", "SKIP_TOO_NEW"):
    candidate = {
        "relpath": "Streams/Image/2023/Unsafe.png",
        "operation": operation,
        "policy_version": None,
        "reason": "test",
        "target": {},
        "executable": False,
    }

    result = mm.apply_filename_policy(dict(candidate), {
        "relpath": candidate["relpath"],
        "best_date": "2023-01-01",
        "detected_kind": "image",
    }, cfg())

    assert result["operation"] == operation, result
    assert result["executable"] is False, result


print("filename policy regression: PASS")
