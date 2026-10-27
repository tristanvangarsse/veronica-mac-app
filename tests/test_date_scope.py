#!/usr/bin/env python3

import datetime as dt
import tempfile
from pathlib import Path

import media_audit as audit
import media_maintenance as mm


def row(date: str):
    return {
        "relpath": "Streams/Image/2023/example.jpg",
        "detected_kind": "image",
        "extension_kind": "image",
        "extension": ".jpg",
        "tags": [],
        "is_symlink": False,
        "cross_filesystem": False,
        "best_date": date,
        "date_confidence": "HIGH",
        "size": 100,
        "probe_error": None,
        "animated": False,
        "expected_kind": "image",
        "folder_year_mismatch": False,
    }


def make_auditor(root: Path, state: Path, scope: dict):
    cfg = dict(audit.DEFAULT_CONFIG)
    cfg["date_scope"] = scope
    return audit.Auditor(
        root,
        cfg,
        dt.date(2026, 9, 24),
        state,
        full_hashing=False,
        probe_media=False,
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        root = base / "media"
        state = base / "state"
        (root / "Streams" / "Image" / "2023").mkdir(parents=True)
        state.mkdir()

        a = make_auditor(root, state, {
            "mode": "within",
            "start": "2020-01-01",
            "end": "2024-12-31",
        })
        assert a.decide(row("2020-01-01")).action == "CANDIDATE"
        assert a.decide(row("2024-12-31")).action == "CANDIDATE"
        assert a.decide(row("2019-12-31")).reason == "date_scope_excluded"
        assert a.decide(row("2025-01-01")).reason == "date_scope_excluded"

        a = make_auditor(root, state, {
            "mode": "outside",
            "start": "2020-01-01",
            "end": "2024-12-31",
        })
        assert a.decide(row("2019-12-31")).action == "CANDIDATE"
        assert a.decide(row("2025-01-01")).action == "CANDIDATE"
        assert a.decide(row("2020-01-01")).reason == "date_scope_excluded"
        assert a.decide(row("2024-12-31")).reason == "date_scope_excluded"

        a = make_auditor(root, state, {"mode": "all"})
        assert a.decide(row("2026-09-24")).action == "CANDIDATE"

        unknown = row("2023-01-01")
        unknown["best_date"] = None
        unknown["date_confidence"] = "UNKNOWN"
        assert a.decide(unknown).action == "REVIEW"

        settings = mm.date_scope_product_settings(state, dt.date(2026, 9, 24))
        assert settings["mode"] == "older_than_two_years"
        assert settings["end"] == "2024-09-23"

    print("date scope regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
