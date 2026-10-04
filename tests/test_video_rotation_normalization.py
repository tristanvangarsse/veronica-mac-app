#!/usr/bin/env python3

def rotation_preserved(
    source_rotation,
    output_rotation,
    full_frame_geometry_preserved,
    display_aspect_ratio_preserved,
):
    source_rotation = int(source_rotation or 0) % 360
    output_rotation = int(output_rotation or 0) % 360

    rotation_metadata_equal = source_rotation == output_rotation
    rotation_baked_into_pixels = (
        source_rotation in {90, 270}
        and output_rotation == 0
        and bool(full_frame_geometry_preserved)
        and bool(display_aspect_ratio_preserved)
    )

    return rotation_metadata_equal or rotation_baked_into_pixels


# Ordinary unchanged orientation.
assert rotation_preserved(0, 0, True, True)
assert rotation_preserved(90, 90, True, True)
assert rotation_preserved(270, 270, True, True)

# HandBrake may bake quarter-turn display-matrix rotation into pixels.
assert rotation_preserved(270, 0, True, True)
assert rotation_preserved(90, 0, True, True)

# But normalization is not trusted if geometry or DAR changed.
assert not rotation_preserved(270, 0, False, True)
assert not rotation_preserved(270, 0, True, False)

# Do not silently waive arbitrary rotation changes.
assert not rotation_preserved(0, 90, True, True)
assert not rotation_preserved(180, 0, True, True)
assert not rotation_preserved(90, 180, True, True)

print("video rotation normalization regression: PASS")
