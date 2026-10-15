import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import media_maintenance as mm


def make_item(relpath, final_relpath):
    return {
        "asset_id": 1,
        "relpath": relpath,
        "source_quick_hash": "abc",
        "source_size": 100,
        "source_mtime_ns": 1,
        "operation": "RENAME",
        "policy_version": "filename-standardization-v1",
        "reason": "filename_not_canonical",
        "target": {
            "final_relpath": final_relpath,
            "filename_standardization": True,
        },
        "executable": True,
    }


def apply_collision_logic(items, occupied_paths=()):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("""
        CREATE TABLE assets (
            asset_id INTEGER PRIMARY KEY,
            relpath TEXT UNIQUE NOT NULL,
            active INTEGER NOT NULL
        )
    """)
    for idx, relpath in enumerate(occupied_paths, 1):
        con.execute(
            "INSERT INTO assets(asset_id, relpath, active) VALUES(?,?,1)",
            (idx, relpath),
        )

    items = mm.resolve_filename_collisions(con, items)

    con.close()
    return items


# 1. Two independent files converging on one destination are disambiguated.
items = [
    make_item(
        "Streams/Image/2023/foo.png",
        "Streams/Image/2023/2023-01-01_same.png",
    ),
    make_item(
        "Streams/Image/2023/bar.png",
        "Streams/Image/2023/2023-01-01_same.png",
    ),
]

result = apply_collision_logic(items)

assert all(i["operation"] == "RENAME" for i in result), result
assert all(i["reason"] == "filename_not_canonical" for i in result), result
assert all(i["executable"] is True for i in result), result
assert result[0]["target"]["final_relpath"] == "Streams/Image/2023/2023-01-01_same-2.png", result
assert result[1]["target"]["final_relpath"] == "Streams/Image/2023/2023-01-01_same.png", result


# 2. Destination occupied by another active archive asset receives a suffix.
items = [
    make_item(
        "Streams/Image/2023/foo.png",
        "Streams/Image/2023/2023-01-01_foo.png",
    ),
]

result = apply_collision_logic(
    items,
    occupied_paths=["Streams/Image/2023/2023-01-01_foo.png"],
)

assert result[0]["operation"] == "RENAME", result
assert result[0]["reason"] == "filename_not_canonical", result
assert result[0]["executable"] is True, result
assert result[0]["target"]["final_relpath"] == "Streams/Image/2023/2023-01-01_foo-2.png", result
assert result[0]["target"]["filename_disambiguated"] is True, result


# 3. Unique, unoccupied canonical rename remains executable.
items = [
    make_item(
        "Streams/Image/2023/foo.png",
        "Streams/Image/2023/2023-01-01_foo.png",
    ),
]

result = apply_collision_logic(items)

assert result[0]["operation"] == "RENAME", result
assert result[0]["reason"] == "filename_not_canonical", result
assert result[0]["executable"] is True, result


print("filename collision policy regression: PASS")
